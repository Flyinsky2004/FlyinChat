from __future__ import annotations

import logging
import time
from uuid import uuid4
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger("flyinchat.tools.permission")


class RequestStatus(Enum):
    CREATED = "CREATED"
    PENDING_USER_APPROVAL = "PENDING_USER_APPROVAL"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    EXECUTED = "EXECUTED"
    FAILED_AFTER_APPROVAL = "FAILED_AFTER_APPROVAL"


_TERMINAL_STATES = frozenset({
    RequestStatus.DENIED,
    RequestStatus.EXPIRED,
    RequestStatus.CANCELLED,
    RequestStatus.EXECUTED,
    RequestStatus.FAILED_AFTER_APPROVAL,
})

_TRANSITIONS: dict[RequestStatus, frozenset[RequestStatus]] = {
    RequestStatus.CREATED: frozenset({RequestStatus.PENDING_USER_APPROVAL}),
    RequestStatus.PENDING_USER_APPROVAL: frozenset({
        RequestStatus.APPROVED,
        RequestStatus.DENIED,
        RequestStatus.EXPIRED,
        RequestStatus.CANCELLED,
    }),
    RequestStatus.APPROVED: frozenset({
        RequestStatus.EXECUTED,
        RequestStatus.FAILED_AFTER_APPROVAL,
    }),
}


@dataclass(frozen=True)
class PermissionRequest:
    request_id: str
    session_id: str
    turn_id: str
    tool_call_id: str
    tool_name: str
    args_preview: str
    risk_level: str
    reason: str
    status: RequestStatus
    created_at: float
    expires_at: float
    resolved_at: float | None = None
    resolved_by: str = ""
    resolution: str = ""

    @classmethod
    def create(
        cls,
        session_id: str,
        turn_id: str,
        tool_call_id: str,
        tool_name: str,
        args_preview: str,
        risk_level: str,
        reason: str,
        timeout_seconds: float = 120.0,
    ) -> PermissionRequest:
        now = time.time()
        return cls(
            request_id=str(uuid4()),
            session_id=session_id,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            args_preview=args_preview,
            risk_level=risk_level,
            reason=reason,
            status=RequestStatus.CREATED,
            created_at=now,
            expires_at=now + timeout_seconds,
        )

    def with_status(self, status: RequestStatus, **extra: Any) -> PermissionRequest:
        _validate_transition(self.status, status)
        kwargs: dict[str, Any] = {"status": status}
        if status in (RequestStatus.APPROVED, RequestStatus.DENIED):
            kwargs["resolved_at"] = extra.get("resolved_at", time.time())
            kwargs["resolved_by"] = extra.get("resolved_by", "user")
            kwargs["resolution"] = extra.get("resolution", status.name.lower())
        elif status == RequestStatus.EXPIRED:
            kwargs["resolved_at"] = extra.get("resolved_at", time.time())
            kwargs["resolved_by"] = "system"
            kwargs["resolution"] = "timeout"
        elif status == RequestStatus.CANCELLED:
            kwargs["resolved_at"] = extra.get("resolved_at", time.time())
            kwargs["resolved_by"] = extra.get("resolved_by", "system")
            kwargs["resolution"] = "cancel"
        return _replace(self, **kwargs)

    def is_terminal(self) -> bool:
        return self.status in _TERMINAL_STATES

    def is_pending(self) -> bool:
        return self.status == RequestStatus.PENDING_USER_APPROVAL

    def is_approved(self) -> bool:
        return self.status == RequestStatus.APPROVED

    def is_expired(self, now: float | None = None) -> bool:
        if now is None:
            now = time.time()
        return self.status == RequestStatus.PENDING_USER_APPROVAL and now >= self.expires_at


def _replace(obj: PermissionRequest, **kwargs: Any) -> PermissionRequest:
    fields = {f.name: getattr(obj, f.name) for f in obj.__dataclass_fields__.values()}
    fields.update(kwargs)
    return PermissionRequest(**fields)


def _validate_transition(current: RequestStatus, next_status: RequestStatus) -> None:
    valid = _TRANSITIONS.get(current, frozenset())
    if next_status not in valid:
        raise ValueError(f"Invalid transition: {current.value} -> {next_status.value}")


class PermissionRequestStore:
    def __init__(self) -> None:
        self._requests: dict[str, PermissionRequest] = {}

    def save(self, request: PermissionRequest) -> None:
        self._requests[request.request_id] = request
        logger.info(
            "permission request saved",
            extra={
                "request_id": request.request_id,
                "tool_name": request.tool_name,
                "status": request.status.value,
            },
        )

    def get(self, request_id: str) -> PermissionRequest | None:
        return self._requests.get(request_id)

    def update_status(
        self, request_id: str, status: RequestStatus, **extra: Any
    ) -> PermissionRequest | None:
        req = self._requests.get(request_id)
        if req is None:
            logger.warning("permission request not found", extra={"request_id": request_id})
            return None
        updated = req.with_status(status, **extra)
        self._requests[request_id] = updated
        logger.info(
            "permission request updated",
            extra={
                "request_id": request_id,
                "tool_name": req.tool_name,
                "old_status": req.status.value,
                "new_status": updated.status.value,
            },
        )
        return updated

    def list_pending(self) -> list[PermissionRequest]:
        return [
            req for req in self._requests.values()
            if req.status == RequestStatus.PENDING_USER_APPROVAL
        ]

    def cancel_all_pending(self) -> list[PermissionRequest]:
        cancelled: list[PermissionRequest] = []
        for req in self.list_pending():
            updated = req.with_status(RequestStatus.CANCELLED)
            self._requests[req.request_id] = updated
            cancelled.append(updated)
        return cancelled

    def expire_stale(self) -> list[PermissionRequest]:
        now = time.time()
        expired: list[PermissionRequest] = []
        for req in self.list_pending():
            if req.is_expired(now):
                updated = req.with_status(RequestStatus.EXPIRED)
                self._requests[req.request_id] = updated
                expired.append(updated)
        return expired


def sanitize_args(tool_input: dict[str, Any], max_value_len: int = 80) -> str:
    parts: list[str] = []
    for k, v in tool_input.items():
        s = str(v)
        if len(s) > max_value_len:
            s = s[:max_value_len] + "..."
        parts.append(f"{k}={s}")
    return ", ".join(parts)
