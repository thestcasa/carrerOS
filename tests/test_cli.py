from __future__ import annotations

import json
from base64 import b64decode
from pathlib import Path

from app.__main__ import main
from app.db import build_engine
from app.domain.models import Base


def test_validate_candidate_cli(
    example_candidates_root: Path, monkeypatch: object, capsys: object
) -> None:
    monkeypatch.setenv("CANDIDATES_ROOT", str(example_candidates_root))  # type: ignore[attr-defined]
    assert main(["validate-candidate", "--candidate", "example_candidate"]) == 0
    result = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert result["status"] == "valid"


def test_readiness_cli(example_candidates_root: Path, monkeypatch: object, capsys: object) -> None:
    monkeypatch.setenv("CANDIDATES_ROOT", str(example_candidates_root))  # type: ignore[attr-defined]
    assert main(["readiness", "--candidate", "example_candidate"]) == 0
    result = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert result["status"] == "ready"


def test_onboard_and_export_candidate_cli(
    copied_candidates_root: Path, tmp_path: Path, monkeypatch: object, capsys: object
) -> None:
    monkeypatch.setenv("CANDIDATES_ROOT", str(copied_candidates_root))  # type: ignore[attr-defined]
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cli.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)  # type: ignore[attr-defined]
    monkeypatch.setenv("RUNTIME_ROOT", str(tmp_path / "runtime"))  # type: ignore[attr-defined]
    Base.metadata.create_all(build_engine(database_url))
    assert (
        main(
            [
                "onboard",
                "--candidate",
                "fictional_friend",
                "--display-name",
                "Fictional Friend",
                "--idempotency-key",
                "onboard-fictional-friend",
            ]
        )
        == 0
    )
    onboarded = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert onboarded["status"] == "draft_unapproved"
    assert main(["export-candidate", "--candidate", "fictional_friend"]) == 0
    exported = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert exported["candidate_id"] == "fictional_friend"
    identity = next(
        item for item in exported["files"] if item["path"] == "configuration/identity.json"
    )
    assert json.loads(b64decode(identity["content_base64"]))["email"].endswith(".invalid")


def test_import_cv_cli_applies_unapproved_fictional_draft(
    copied_candidates_root: Path, tmp_path: Path, monkeypatch: object, capsys: object
) -> None:
    monkeypatch.setenv("CANDIDATES_ROOT", str(copied_candidates_root))  # type: ignore[attr-defined]
    cv_path = tmp_path / "fictional.txt"
    cv_path.write_text(
        """EXPERIENCE
Fictional Labs | Research Engineer | Remote | 2020-01 | 2022-12 | Python
- Built a fictional evaluation fixture.
""",
        encoding="utf-8",
    )

    assert (
        main(
            [
                "import-cv",
                "--candidate",
                "example_candidate",
                "--file",
                str(cv_path),
                "--apply",
                "--idempotency-key",
                "import-fictional-cv",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert result["status"] == "applied_unapproved"
    assert result["profile_version"] == "1.0.1"


def test_configuration_export_and_import_cli(
    copied_candidates_root: Path,
    tmp_path: Path,
    monkeypatch: object,
    capsys: object,
) -> None:
    monkeypatch.setenv("CANDIDATES_ROOT", str(copied_candidates_root))  # type: ignore[attr-defined]
    bundle = tmp_path / "candidate.yaml"

    assert (
        main(
            [
                "export-configuration",
                "--candidate",
                "example_candidate",
                "--format",
                "yaml",
                "--file",
                str(bundle),
            ]
        )
        == 0
    )
    assert bundle.read_text(encoding="utf-8").startswith("candidate_id: example_candidate")
    assert (
        main(
            [
                "import-configuration",
                "--candidate",
                "example_candidate",
                "--file",
                str(bundle),
                "--expected-profile-version",
                "1.0.0",
                "--idempotency-key",
                "configuration-cli-import",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert result["changed"] is False
    assert result["profile_version"] == "1.0.0"
