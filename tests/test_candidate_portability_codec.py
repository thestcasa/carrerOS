from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import pytest

from app.candidates.loader import CandidateLoader
from app.candidates.portability import (
    MAX_CONFIGURATION_BUNDLE_BYTES,
    CandidatePortabilityError,
    build_configuration_bundle,
    dump_configuration_bundle,
    parse_configuration_bundle,
)


@pytest.mark.parametrize("format", ("json", "yaml"))
def test_configuration_bundle_round_trip_is_deterministic(
    example_candidates_root: Path,
    format: Literal["json", "yaml"],
) -> None:
    config = CandidateLoader(example_candidates_root).load("example_candidate")
    bundle = build_configuration_bundle(config)

    first = dump_configuration_bundle(bundle, format)
    parsed = parse_configuration_bundle(
        first,
        format,
        expected_candidate_id="example_candidate",
    )

    assert parsed == bundle
    assert dump_configuration_bundle(parsed, format) == first


def test_duplicate_json_and_yaml_keys_are_rejected() -> None:
    for content, format in (
        ('{"kind":"one","kind":"two"}', "json"),
        ("kind: one\nkind: two\n", "yaml"),
    ):
        with pytest.raises(CandidatePortabilityError) as caught:
            parse_configuration_bundle(
                content,
                format,  # type: ignore[arg-type]
                expected_candidate_id="example_candidate",
            )

        assert caught.value.code == "candidate_import_invalid"


def test_non_finite_json_number_is_rejected() -> None:
    with pytest.raises(CandidatePortabilityError) as caught:
        parse_configuration_bundle(
            '{"value":NaN}',
            "json",
            expected_candidate_id="example_candidate",
        )

    assert caught.value.code == "candidate_import_invalid"


@pytest.mark.parametrize(
    "content",
    (
        "root: &shared [one]\ncopy: *shared\n",
        "root: !unsafe value\n",
        "root: !!python/object:builtins.str {}\n",
    ),
)
def test_unsafe_yaml_features_are_rejected(content: str) -> None:
    with pytest.raises(CandidatePortabilityError) as caught:
        parse_configuration_bundle(
            content,
            "yaml",
            expected_candidate_id="example_candidate",
        )

    assert caught.value.code == "candidate_import_invalid"


def test_tampered_hash_and_wrong_candidate_are_rejected(
    example_candidates_root: Path,
) -> None:
    config = CandidateLoader(example_candidates_root).load("example_candidate")
    content = dump_configuration_bundle(build_configuration_bundle(config), "json")
    tampered = json.loads(content)
    tampered["configuration"]["biography"]["summary"] = "Tampered summary"

    with pytest.raises(CandidatePortabilityError) as caught:
        parse_configuration_bundle(
            json.dumps(tampered),
            "json",
            expected_candidate_id="example_candidate",
        )
    assert caught.value.code == "candidate_import_invalid"

    with pytest.raises(CandidatePortabilityError) as caught:
        parse_configuration_bundle(
            content,
            "json",
            expected_candidate_id="different_candidate",
        )
    assert caught.value.code == "candidate_import_candidate_mismatch"
    assert "example_candidate" not in str(caught.value)


def test_excessive_size_and_depth_are_rejected() -> None:
    with pytest.raises(CandidatePortabilityError) as caught:
        parse_configuration_bundle(
            "x" * (MAX_CONFIGURATION_BUNDLE_BYTES + 1),
            "json",
            expected_candidate_id="example_candidate",
        )
    assert caught.value.code == "candidate_import_too_large"

    content = "value: " + ("[" * 41) + "0" + ("]" * 41)
    with pytest.raises(CandidatePortabilityError) as caught:
        parse_configuration_bundle(
            content,
            "yaml",
            expected_candidate_id="example_candidate",
        )
    assert caught.value.code == "candidate_import_invalid"
