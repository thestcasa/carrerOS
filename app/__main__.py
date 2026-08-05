from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

from app.candidates.loader import CandidateConfigError, CandidateLoader
from app.candidates.readiness import assess_readiness
from app.candidates.service import CandidateCreateRequest, CandidateService
from app.core.settings import Settings
from app.db import build_engine, build_session_factory
from app.job_service import DiscoveryRequest, JobService
from app.runtime import run_process


def _candidates_root() -> Path:
    configured = os.getenv("CANDIDATES_ROOT")
    return Path(configured) if configured else Path.cwd() / "candidates"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate-candidate", "readiness"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--candidate", required=True)
    onboard = subparsers.add_parser("onboard")
    onboard.add_argument("--candidate", required=True)
    onboard.add_argument("--display-name")
    export = subparsers.add_parser("export-candidate")
    export.add_argument("--candidate", required=True)
    discover = subparsers.add_parser("discover")
    discover.add_argument("--candidate", required=True)
    discover.add_argument(
        "--fixture",
        type=Path,
        help="JSON fixture with platform, company, company_domain, and payloads.",
    )
    subparsers.add_parser("run-worker")
    subparsers.add_parser("run-scheduler")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in {"run-worker", "run-scheduler"}:
        run_process(args.command.removeprefix("run-"))

    candidate_service = CandidateService(_candidates_root())
    if args.command == "onboard":
        detail = candidate_service.create(
            CandidateCreateRequest(
                candidate_id=args.candidate,
                display_name=args.display_name or args.candidate.replace("_", " ").title(),
            )
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
        print(json.dumps(candidate_service.export(args.candidate), sort_keys=True))
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
            )
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
