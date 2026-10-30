"""
Structured Security Audit Logging Service (Track P9 / Ticket P9-12)
Emits structured JSON logs for authentication lifecycle, token revocation/rotation,
billing webhooks, and security defense violations.
"""

from datetime import datetime, timezone
import json
import logging
from typing import Any

audit_logger = logging.getLogger("app.security_audit")


class SecurityJsonFormatter(logging.Formatter):
    """Custom logging formatter rendering log records as valid single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        if hasattr(record, "audit_payload"):
            data.update(record.audit_payload)
        return json.dumps(data)


def log_security_event(
    event: str,
    user_id: str | None = None,
    ip_address: str | None = None,
    status: str = "SUCCESS",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Emit a structured JSON audit event.

    Args:
        event: Dot-delimited event name, e.g. 'auth.login_failed', 'billing.webhook_verified'.
        user_id: User identifier (email or UUID) if authenticated/provided.
        ip_address: Client IP address.
        status: Event outcome, e.g. 'SUCCESS', 'FAILURE', 'BLOCKED'.
        details: Additional contextual metadata.

    Returns:
        The generated structured audit payload dictionary.
    """
    payload: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "status": status,
        "user_id": user_id,
        "ip_address": ip_address,
        "details": details or {},
    }

    audit_logger.info(
        json.dumps(payload),
        extra={"audit_payload": payload},
    )
    return payload
