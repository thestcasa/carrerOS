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

    @classmethod
    def from_environment(cls) -> Settings:
        origins = os.getenv("CORS_ORIGINS", "http://localhost:3000")
        return cls(
            database_url=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            candidates_root=Path(os.getenv("CANDIDATES_ROOT", Path.cwd() / "candidates")),
            cors_origins=tuple(origin.strip() for origin in origins.split(",") if origin.strip()),
        )
