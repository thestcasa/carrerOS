from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AuthModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExpiringClaims(AuthModel):
    issued_at: datetime
    expires_at: datetime


class SessionClaims(ExpiringClaims):
    token_type: Literal["session"] = "session"
    session_id: str = Field(min_length=8)
    user_id: str = Field(min_length=1)
    candidate_ids: tuple[str, ...]


class CsrfClaims(ExpiringClaims):
    token_type: Literal["csrf"] = "csrf"
    session_id: str = Field(min_length=8)
    nonce: str = Field(min_length=8)


class ArtifactClaims(ExpiringClaims):
    token_type: Literal["artifact"] = "artifact"
    user_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    artifact_path: str = Field(min_length=1)


class RateLimitDecision(AuthModel):
    allowed: bool
    limit: int = Field(ge=1)
    remaining: int = Field(ge=0)
    reset_at: datetime


class AdminAuditEvent(AuthModel):
    sequence: int = Field(ge=1)
    occurred_at: datetime
    admin_user_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    candidate_id: str | None = None
    details: tuple[tuple[str, str], ...] = ()
    previous_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    event_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class DataPlanItem(AuthModel):
    category: Literal["configuration", "database", "artifacts", "browser_session", "audit"]
    locator: str = Field(min_length=1)
    action: Literal["include", "delete", "retain"]
    reason: str = Field(min_length=1)


class CandidateDataPlan(AuthModel):
    operation: Literal["export", "delete"]
    candidate_id: str = Field(min_length=1)
    created_at: datetime
    executable: Literal[False] = False
    items: tuple[DataPlanItem, ...]
    warnings: tuple[str, ...] = ()
