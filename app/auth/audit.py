from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock

from app.auth.contracts import AdminAuditEvent

_GENESIS_HASH = "0" * 64


class AdminAuditLog:
    def __init__(self, *, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(UTC))
        self._events: list[AdminAuditEvent] = []
        self._lock = Lock()

    def record(
        self,
        *,
        admin_user_id: str,
        action: str,
        candidate_id: str | None = None,
        details: tuple[tuple[str, str], ...] = (),
    ) -> AdminAuditEvent:
        with self._lock:
            previous_hash = self._events[-1].event_hash if self._events else _GENESIS_HASH
            data = {
                "sequence": len(self._events) + 1,
                "occurred_at": self._now().astimezone(UTC).isoformat(),
                "admin_user_id": admin_user_id,
                "action": action,
                "candidate_id": candidate_id,
                "details": sorted(details),
                "previous_hash": previous_hash,
            }
            event_hash = hashlib.sha256(
                json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            event = AdminAuditEvent(**data, event_hash=event_hash)
            self._events.append(event)
            return event

    def events(self) -> tuple[AdminAuditEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def verify(self) -> bool:
        previous_hash = _GENESIS_HASH
        for event in self.events():
            data = {
                "sequence": event.sequence,
                "occurred_at": event.occurred_at.isoformat(),
                "admin_user_id": event.admin_user_id,
                "action": event.action,
                "candidate_id": event.candidate_id,
                "details": sorted(event.details),
                "previous_hash": event.previous_hash,
            }
            expected = hashlib.sha256(
                json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if event.previous_hash != previous_hash or event.event_hash != expected:
                return False
            previous_hash = event.event_hash
        return True
