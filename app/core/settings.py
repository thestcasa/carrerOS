from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.db import DEFAULT_DATABASE_URL


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    redis_url: str
    candidates_root: Path
    cors_origins: tuple[str, ...]
    runtime_root: Path = Path.cwd() / "runtime"
    auth_required: bool = False
    local_token_secret: str | None = None
    controlled_submission_enabled: bool = False

    @classmethod
    def from_environment(cls) -> Settings:
        origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
        return cls(
            database_url=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            candidates_root=Path(os.getenv("CANDIDATES_ROOT", Path.cwd() / "candidates")),
            cors_origins=tuple(origin.strip() for origin in origins.split(",") if origin.strip()),
            runtime_root=Path(os.getenv("RUNTIME_ROOT", Path.cwd() / "runtime")),
            auth_required=os.getenv("AUTH_REQUIRED", "true").casefold() == "true",
            local_token_secret=os.getenv("LOCAL_TOKEN_SECRET"),
            controlled_submission_enabled=(
                os.getenv("CONTROLLED_SUBMISSION_ENABLED", "false").casefold() == "true"
            ),
        )
