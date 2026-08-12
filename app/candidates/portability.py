from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, cast

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from yaml.events import AliasEvent  # type: ignore[import-untyped]

from app.candidates.models import CandidateConfig

MAX_CONFIGURATION_BUNDLE_BYTES = 1024 * 1024
_MAX_NODES = 20_000
_MAX_DEPTH = 40


class CandidatePortabilityError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical_configuration_bytes(configuration: CandidateConfig) -> bytes:
    return json.dumps(
        configuration.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


class CandidateConfigurationBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["careeros_candidate_configuration"] = "careeros_candidate_configuration"
    schema_version: Literal["1.0"] = "1.0"
    candidate_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    source_profile_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    configuration: CandidateConfig
    configuration_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def identity_and_hash_match(self) -> CandidateConfigurationBundle:
        if (
            self.configuration.manifest.candidate_id != self.candidate_id
            or self.configuration.identity.candidate_id != self.candidate_id
        ):
            raise ValueError("bundle candidate identity does not match its configuration")
        if self.configuration.manifest.profile_version != self.source_profile_version:
            raise ValueError("bundle source version does not match its configuration")
        digest = hashlib.sha256(canonical_configuration_bytes(self.configuration)).hexdigest()
        if digest != self.configuration_sha256:
            raise ValueError("bundle configuration hash does not match")
        return self


def build_configuration_bundle(configuration: CandidateConfig) -> CandidateConfigurationBundle:
    return CandidateConfigurationBundle(
        candidate_id=configuration.manifest.candidate_id,
        source_profile_version=configuration.manifest.profile_version,
        configuration=configuration,
        configuration_sha256=hashlib.sha256(
            canonical_configuration_bytes(configuration)
        ).hexdigest(),
    )


def dump_configuration_bundle(
    bundle: CandidateConfigurationBundle,
    format: Literal["json", "yaml"],
) -> str:
    payload = bundle.model_dump(mode="json")
    if format == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if format == "yaml":
        return cast(str, yaml.safe_dump(payload, allow_unicode=True, sort_keys=True))
    raise CandidatePortabilityError("candidate_import_unsupported", "Unsupported bundle format.")


class _UniqueKeyLoader(yaml.SafeLoader):  # type: ignore[misc]
    pass


def _construct_unique_mapping(
    loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError as exc:
            raise CandidatePortabilityError(
                "candidate_import_invalid", "Bundle mapping key is invalid."
            ) from exc
        if duplicate:
            raise CandidatePortabilityError(
                "candidate_import_invalid", "Bundle contains a duplicate mapping key."
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CandidatePortabilityError(
                "candidate_import_invalid", "Bundle contains a duplicate mapping key."
            )
        result[key] = value
    return result


def _invalid_json_constant(_value: str) -> None:
    raise CandidatePortabilityError(
        "candidate_import_invalid", "Bundle contains a non-finite JSON number."
    )


def _bounded_tree(value: Any, *, depth: int = 0, count: list[int] | None = None) -> None:
    counter = count if count is not None else [0]
    counter[0] += 1
    if counter[0] > _MAX_NODES or depth > _MAX_DEPTH:
        raise CandidatePortabilityError(
            "candidate_import_invalid", "Bundle structure exceeds safe limits."
        )
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise CandidatePortabilityError(
                    "candidate_import_invalid", "Bundle mapping keys must be strings."
                )
            _bounded_tree(child, depth=depth + 1, count=counter)
    elif isinstance(value, list):
        for child in value:
            _bounded_tree(child, depth=depth + 1, count=counter)


def parse_configuration_bundle(
    content: str,
    format: Literal["json", "yaml"],
    *,
    expected_candidate_id: str,
) -> CandidateConfigurationBundle:
    try:
        content_size = len(content.encode("utf-8"))
    except UnicodeError as exc:
        raise CandidatePortabilityError(
            "candidate_import_invalid", "Candidate configuration bundle is invalid."
        ) from exc
    if content_size > MAX_CONFIGURATION_BUNDLE_BYTES:
        raise CandidatePortabilityError(
            "candidate_import_too_large", "Candidate configuration bundle exceeds 1 MiB."
        )
    try:
        if format == "json":
            payload = json.loads(
                content,
                object_pairs_hook=_json_object,
                parse_constant=_invalid_json_constant,
            )
        elif format == "yaml":
            if any(isinstance(event, AliasEvent) for event in yaml.parse(content)):
                raise CandidatePortabilityError(
                    "candidate_import_invalid", "YAML aliases are not permitted."
                )
            payload = yaml.load(content, Loader=_UniqueKeyLoader)
        else:
            raise CandidatePortabilityError(
                "candidate_import_unsupported", "Unsupported bundle format."
            )
        _bounded_tree(payload)
        bundle = CandidateConfigurationBundle.model_validate(payload)
    except CandidatePortabilityError:
        raise
    except (
        UnicodeError,
        json.JSONDecodeError,
        yaml.YAMLError,
        ValidationError,
        RecursionError,
        OverflowError,
        ValueError,
    ) as exc:
        raise CandidatePortabilityError(
            "candidate_import_invalid", "Candidate configuration bundle is invalid."
        ) from exc
    if bundle.candidate_id != expected_candidate_id:
        raise CandidatePortabilityError(
            "candidate_import_candidate_mismatch",
            "Candidate configuration bundle belongs to another candidate.",
        )
    return bundle
