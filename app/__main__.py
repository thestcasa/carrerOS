from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from app.auth.lifecycle import CandidateDeletionRequest, CandidateLifecycleService
from app.candidates.cv_import import CVImportRequest
from app.candidates.loader import CandidateConfigError, CandidateLoader
from app.candidates.readiness import assess_readiness
from app.candidates.service import (
    CandidateConfigurationImportRequest,
    CandidateCreateRequest,
    CandidateService,
)
from app.core.settings import Settings
from app.db import build_engine, build_session_factory
from app.job_service import DiscoveryRequest, JobService
from app.runtime import run_process


def _candidates_root() -> Path:
    configured = os.getenv("CANDIDATES_ROOT")
    return Path(configured) if configured else Path.cwd() / "candidates"


def _idempotency_key(value: str) -> str:
    if not 8 <= len(value) <= 128:
        raise argparse.ArgumentTypeError("idempotency key must contain 8 to 128 characters")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate-candidate", "readiness"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--candidate", required=True)
    onboard = subparsers.add_parser("onboard")
    onboard.add_argument("--candidate", required=True)
    onboard.add_argument("--display-name")
    onboard.add_argument("--idempotency-key", required=True, type=_idempotency_key)
    export = subparsers.add_parser("export-candidate")
    export.add_argument("--candidate", required=True)
    export_configuration = subparsers.add_parser("export-configuration")
    export_configuration.add_argument("--candidate", required=True)
    export_configuration.add_argument("--format", choices=("json", "yaml"), default="json")
    export_configuration.add_argument("--file", type=Path)
    import_configuration = subparsers.add_parser("import-configuration")
    import_configuration.add_argument("--candidate", required=True)
    import_configuration.add_argument("--file", type=Path, required=True)
    import_configuration.add_argument("--expected-profile-version", required=True)
    import_configuration.add_argument("--idempotency-key", required=True, type=_idempotency_key)
    delete_candidate = subparsers.add_parser("delete-candidate")
    delete_candidate.add_argument("--candidate", required=True)
    delete_candidate.add_argument("--confirmation", required=True)
    delete_candidate.add_argument("--idempotency-key", required=True, type=_idempotency_key)
    deletion_status = subparsers.add_parser("deletion-status")
    deletion_status.add_argument("--candidate", required=True)
    cv_import = subparsers.add_parser("import-cv")
    cv_import.add_argument("--candidate", required=True)
    cv_import.add_argument("--file", type=Path, required=True)
    cv_import.add_argument("--apply", action="store_true")
    cv_import.add_argument("--idempotency-key", required=True, type=_idempotency_key)
    discover = subparsers.add_parser("discover")
    discover.add_argument("--candidate", required=True)
    discover.add_argument(
        "--fixture",
        type=Path,
        help="JSON fixture with platform, company, company_domain, and payloads.",
    )
    discover.add_argument("--idempotency-key", required=True, type=_idempotency_key)
    subparsers.add_parser("run-worker")
    subparsers.add_parser("run-browser-worker")
    subparsers.add_parser("run-controlled-submission-worker")
    subparsers.add_parser("run-scheduler")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in {
        "run-worker",
        "run-browser-worker",
        "run-controlled-submission-worker",
        "run-scheduler",
    }:
        run_process(args.command.removeprefix("run-"))

    candidate_service = CandidateService(_candidates_root())
    if args.command == "onboard":
        detail = candidate_service.create(
            CandidateCreateRequest(
                candidate_id=args.candidate,
                display_name=args.display_name or args.candidate.replace("_", " ").title(),
            ),
            args.idempotency_key,
        )
        print(
            json.dumps(
                {
                    "candidate_id": detail.candidate_id,
                    "profile_version": detail.profile_version,
                    "status": "draft_unapproved",
                    "readiness": detail.readiness.status,
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command == "export-candidate":
        settings = Settings.from_environment()
        lifecycle = CandidateLifecycleService(
            build_session_factory(build_engine(settings.database_url)),
            candidate_service,
            settings.runtime_root,
        )
        print(lifecycle.export_candidate(args.candidate).model_dump_json())
        return 0
    if args.command == "export-configuration":
        content = candidate_service.export_configuration(args.candidate, args.format)
        if args.file is None:
            sys.stdout.write(content)
        else:
            args.file.write_text(content, encoding="utf-8")
        return 0
    if args.command == "import-configuration":
        suffix = args.file.suffix.casefold()
        format = "yaml" if suffix in {".yaml", ".yml"} else "json" if suffix == ".json" else None
        if format is None or not args.file.is_file() or args.file.stat().st_size > 1024 * 1024:
            print(
                json.dumps(
                    {
                        "candidate_id": args.candidate,
                        "status": "invalid",
                        "error": "Configuration file must be JSON or YAML and no larger than 1 MiB",
                    },
                    sort_keys=True,
                )
            )
            return 1
        try:
            content = args.file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            print(
                json.dumps(
                    {
                        "candidate_id": args.candidate,
                        "status": "invalid",
                        "error": "Configuration file must be UTF-8 text",
                    },
                    sort_keys=True,
                )
            )
            return 1
        configuration_result = candidate_service.import_configuration(
            args.candidate,
            CandidateConfigurationImportRequest(
                format=format,
                content=content,
                expected_profile_version=args.expected_profile_version,
            ),
            args.idempotency_key,
        )
        print(configuration_result.model_dump_json())
        return 0
    if args.command in {"delete-candidate", "deletion-status"}:
        settings = Settings.from_environment()
        lifecycle = CandidateLifecycleService(
            build_session_factory(build_engine(settings.database_url)),
            candidate_service,
            settings.runtime_root,
        )
        if args.command == "deletion-status":
            print(lifecycle.deletion_status(args.candidate).model_dump_json())
            return 0
        deletion_result = lifecycle.delete_candidate(
            args.candidate,
            CandidateDeletionRequest(
                confirmation=args.confirmation,
                delete_archives=True,
            ),
            args.idempotency_key,
        )
        print(deletion_result.model_dump_json())
        return 0
    if args.command == "import-cv":
        if (
            not args.file.is_file()
            or args.file.suffix.lower() != ".txt"
            or args.file.stat().st_size > 2 * 1024 * 1024
        ):
            print(
                json.dumps(
                    {
                        "candidate_id": args.candidate,
                        "status": "invalid",
                        "error": "CV file must be UTF-8 text and no larger than 2 MiB",
                    },
                    sort_keys=True,
                )
            )
            return 1
        draft = candidate_service.create_cv_import(
            args.candidate,
            CVImportRequest(
                filename=args.file.name,
                content_base64=base64.b64encode(args.file.read_bytes()).decode(),
            ),
            f"{args.idempotency_key}:draft",
        )
        if args.apply:
            detail = candidate_service.apply_cv_import(
                args.candidate, draft.import_id, f"{args.idempotency_key}:apply"
            )
            print(
                json.dumps(
                    {
                        "candidate_id": detail.candidate_id,
                        "import_id": draft.import_id,
                        "profile_version": detail.profile_version,
                        "status": "applied_unapproved",
                    },
                    sort_keys=True,
                )
            )
        else:
            print(draft.model_dump_json())
        return 0
    if args.command == "discover":
        if args.fixture is None:
            print(
                json.dumps(
                    {
                        "candidate_id": args.candidate,
                        "status": "fixture_required",
                        "message": "Supply --fixture for deterministic offline discovery.",
                    },
                    sort_keys=True,
                )
            )
            return 2
        fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
        settings = Settings.from_environment()
        jobs = JobService(
            build_session_factory(build_engine(settings.database_url)), candidate_service
        )
        result = jobs.discover(
            DiscoveryRequest(
                candidate_id=args.candidate,
                platform=fixture["platform"],
                company=fixture["company"],
                company_domain=fixture["company_domain"],
                payloads=tuple(fixture["payloads"]),
            ),
            args.idempotency_key,
        )
        print(result.model_dump_json())
        return 0

    loader = CandidateLoader(_candidates_root())
    try:
        config = loader.load(args.candidate)
    except CandidateConfigError as exc:
        print(
            json.dumps(
                {"candidate_id": args.candidate, "status": "invalid", "error": str(exc)},
                sort_keys=True,
            )
        )
        return 1

    if args.command == "validate-candidate":
        print(
            json.dumps(
                {
                    "candidate_id": config.manifest.candidate_id,
                    "profile_version": config.manifest.profile_version,
                    "schema_version": config.manifest.schema_version,
                    "status": "valid",
                },
                sort_keys=True,
            )
        )
        return 0

    report = assess_readiness(config)
    print(report.model_dump_json())
    return 0 if report.status == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
