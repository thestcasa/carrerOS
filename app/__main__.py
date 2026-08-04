from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

from app.candidates.loader import CandidateConfigError, CandidateLoader
from app.candidates.readiness import assess_readiness


def _candidates_root() -> Path:
    configured = os.getenv("CANDIDATES_ROOT")
    return Path(configured) if configured else Path.cwd() / "candidates"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate-candidate", "readiness"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--candidate", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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
