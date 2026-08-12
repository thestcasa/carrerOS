from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.auth.contracts import ArtifactClaims, CsrfClaims, ExpiringClaims, SessionClaims

ClaimsT = TypeVar("ClaimsT", bound=ExpiringClaims)


class TokenValidationError(ValueError):
    pass


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class LocalTokenService:
    def __init__(self, secret: bytes, *, now: Callable[[], datetime] | None = None) -> None:
        if len(secret) < 32:
            raise ValueError("token secret must contain at least 32 bytes")
        self._secret = secret
        self._now = now or (lambda: datetime.now(UTC))

    def issue_session(
        self,
        *,
        session_id: str,
        user_id: str,
        candidate_ids: tuple[str, ...],
        lifetime: timedelta,
    ) -> str:
        issued_at = self._utc_now()
        claims = SessionClaims(
            session_id=session_id,
            user_id=user_id,
            candidate_ids=tuple(sorted(set(candidate_ids))),
            issued_at=issued_at,
            expires_at=issued_at + lifetime,
        )
        return self._sign(claims)

    def verify_session(self, token: str) -> SessionClaims:
        return self._verify(token, SessionClaims)

    def require_candidate(self, claims: SessionClaims, candidate_id: str) -> None:
        if candidate_id not in claims.candidate_ids:
            raise PermissionError("session does not own the requested candidate")

    def issue_csrf(self, *, session_id: str, lifetime: timedelta) -> str:
        issued_at = self._utc_now()
        return self._sign(
            CsrfClaims(
                session_id=session_id,
                nonce=secrets.token_urlsafe(16),
                issued_at=issued_at,
                expires_at=issued_at + lifetime,
            )
        )

    def verify_csrf(self, token: str, *, session_id: str) -> CsrfClaims:
        claims = self._verify(token, CsrfClaims)
        if not hmac.compare_digest(claims.session_id, session_id):
            raise TokenValidationError("CSRF token is not bound to this session")
        return claims

    def issue_artifact_access(
        self,
        *,
        user_id: str,
        candidate_id: str,
        artifact_path: str,
        lifetime: timedelta,
    ) -> str:
        path = self._safe_artifact_path(artifact_path)
        issued_at = self._utc_now()
        return self._sign(
            ArtifactClaims(
                user_id=user_id,
                candidate_id=candidate_id,
                artifact_path=path,
                issued_at=issued_at,
                expires_at=issued_at + lifetime,
            )
        )

    def verify_artifact_access(
        self,
        token: str,
        *,
        user_id: str,
        candidate_id: str,
        artifact_path: str,
    ) -> ArtifactClaims:
        claims = self._verify(token, ArtifactClaims)
        expected_path = self._safe_artifact_path(artifact_path)
        for actual, expected in (
            (claims.user_id, user_id),
            (claims.candidate_id, candidate_id),
            (claims.artifact_path, expected_path),
        ):
            if not hmac.compare_digest(actual, expected):
                raise TokenValidationError("artifact token scope does not match request")
        return claims

    def _sign(self, claims: BaseModel) -> str:
        payload = json.dumps(
            claims.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
        encoded = _encode(payload)
        signature = _encode(hmac.new(self._secret, encoded.encode(), hashlib.sha256).digest())
        return f"{encoded}.{signature}"

    def _verify(self, token: str, model: type[ClaimsT]) -> ClaimsT:
        try:
            encoded, supplied_signature = token.split(".")
            expected_signature = _encode(
                hmac.new(self._secret, encoded.encode(), hashlib.sha256).digest()
            )
            if not hmac.compare_digest(supplied_signature, expected_signature):
                raise TokenValidationError("token signature is invalid")
            payload: Any = json.loads(_decode(encoded))
            claims = model.model_validate(payload)
        except TokenValidationError:
            raise
        except (ValueError, ValidationError, UnicodeDecodeError) as exc:
            raise TokenValidationError("token is malformed") from exc
        if claims.expires_at <= self._utc_now():
            raise TokenValidationError("token has expired")
        if claims.issued_at > self._utc_now():
            raise TokenValidationError("token was issued in the future")
        return claims

    def _utc_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(UTC)

    @staticmethod
    def _safe_artifact_path(value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or not value or ".." in path.parts or "." in path.parts:
            raise ValueError("artifact path must be a normalized relative path")
        normalized = path.as_posix()
        if normalized != value or value.endswith("/"):
            raise ValueError("artifact path must be a normalized relative path")
        return normalized
