from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

import redis
from pydantic import BaseModel, ConfigDict
from redis.backoff import NoBackoff
from redis.retry import Retry
from sqlalchemy import Engine, text


class ServiceStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["available", "unavailable"]
    detail: str | None = None


class HealthReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok", "degraded"]
    api: ServiceStatus
    database: ServiceStatus
    redis: ServiceStatus


class HealthChecker(Protocol):
    def check(self) -> HealthReport: ...


@dataclass(slots=True)
class HealthProbe:
    engine: Engine
    redis_url: str

    def check(self) -> HealthReport:
        database = self._database_status()
        redis_status = self._redis_status()
        overall = "ok" if database.status == redis_status.status == "available" else "degraded"
        return HealthReport(
            status=overall,
            api=ServiceStatus(status="available"),
            database=database,
            redis=redis_status,
        )

    def _database_status(self) -> ServiceStatus:
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception:
            return ServiceStatus(status="unavailable", detail="Database connection failed.")
        return ServiceStatus(status="available")

    def _redis_status(self) -> ServiceStatus:
        try:
            client = redis.Redis.from_url(
                self.redis_url,
                socket_connect_timeout=1,
                socket_timeout=1,
                retry=Retry(NoBackoff(), 0),
            )
            client.ping()
            client.close()
        except Exception:
            return ServiceStatus(status="unavailable", detail="Redis connection failed.")
        return ServiceStatus(status="available")
