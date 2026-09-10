"""
Audit log for state-changing actions.

Every time the confirmation gate is invoked — whether the technician
confirms, rejects, or the confirmed action fails on execution — a record
is appended here. This is the kind of trail an ISP (or any employer
evaluating this project) expects to exist before trusting an agent with
write access to production infrastructure: who proposed what, why, who
confirmed or rejected it, and what actually happened.

Format: JSON Lines (one JSON object per line) at audit_log.jsonl, so it's
append-only, diff-friendly, and trivially parseable by any log shipper
without needing this project's code.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

AUDIT_LOG_PATH = Path(os.getenv("AUDIT_LOG_PATH", Path(__file__).parent.parent / "audit_log.jsonl"))


def log_action(pending, user_response: str, outcome: dict, technician: str = "unknown") -> None:
    """Append one audit record. Never raises — a logging failure should
    not block or mask the outcome of the action itself."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "technician": technician,
        "site_id": pending.site_id,
        "action": pending.action_name,
        "argument": pending.argument,
        "reason": pending.reason,
        "confirmation_given": user_response,
        "executed": outcome.get("executed", False),
        "outcome": outcome,
    }
    try:
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        # best-effort logging — don't let a disk/permissions issue take
        # down the agent over an audit-log write
        pass


def read_audit_log() -> list[dict]:
    """Read all audit records, for a review tool or the notebook demo."""
    if not AUDIT_LOG_PATH.exists():
        return []
    records = []
    with open(AUDIT_LOG_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records
