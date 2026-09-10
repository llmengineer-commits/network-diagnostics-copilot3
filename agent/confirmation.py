"""
Human-in-the-loop confirmation gate for state-changing router actions.

This is deliberately NOT implemented as a prompted LLM behavior ("please
ask before doing anything destructive"). Prompted behavior is not
reliable enough for actions that touch customer-facing infrastructure —
a model can be talked out of a safety instruction embedded in its own
context. Instead, the gate is enforced in code: the agent can describe
and propose a write action, but the actual write function is never
invoked except through `execute_with_confirmation`, and that function
refuses to proceed unless the user's literal input is "YES".

This means there is no prompt-injection path, no jailbreak, and no
multi-turn social-engineering path from "diagnose this" to "a DHCP lease
just got reset" — the code path for the write functions
(reset_dhcp_lease_raw, restart_pppoe_session_raw) simply does not exist
outside this gate.

Every confirmed (or rejected) action is written to the audit log
(agent/audit_log.py) regardless of outcome, so there's a durable record
of every write the agent ever proposed against live infrastructure.
"""

from dataclasses import dataclass
from typing import Callable

from agent.audit_log import log_action
from agent.tools import RouterAPIError, reset_dhcp_lease_raw, restart_pppoe_session_raw

CONFIRMATION_TOKEN = "YES"

# Maps a proposed action name to the raw (unguarded) function that
# performs it. Only reachable through execute_with_confirmation below.
_ACTIONS: dict[str, Callable[..., dict]] = {
    "reset_dhcp_lease": reset_dhcp_lease_raw,
    "restart_pppoe_session": restart_pppoe_session_raw,
}


@dataclass
class PendingAction:
    action_name: str
    site_id: str
    argument: str
    reason: str

    def confirmation_prompt(self) -> str:
        return (
            f"Proposed action: {self.action_name}(site={self.site_id!r}, {self.argument!r})\n"
            f"Reason: {self.reason}\n"
            f"This will change live router state at site '{self.site_id}'. "
            f"Type YES to proceed, or anything else to cancel."
        )


def propose_action(action_name: str, site_id: str, argument: str, reason: str) -> PendingAction:
    """
    Called by the agent to propose a write action. This does NOT execute
    anything — it only builds the confirmation prompt that must be shown
    to the user before execute_with_confirmation can run.
    """
    if action_name not in _ACTIONS:
        raise ValueError(f"unknown action '{action_name}'")
    return PendingAction(action_name=action_name, site_id=site_id, argument=argument, reason=reason)


def execute_with_confirmation(pending: PendingAction, user_response: str, technician: str = "unknown") -> dict:
    """
    The ONLY function that can actually invoke a write action. Requires
    the user's response to be the exact literal string "YES" (case-
    sensitive, no fuzzy matching) — deliberately strict, so there's no
    ambiguity about what counts as consent. Every call — confirmed,
    rejected, or failed — is written to the audit log.
    """
    if user_response != CONFIRMATION_TOKEN:
        outcome = {
            "executed": False,
            "reason": (
                f"Action cancelled — confirmation was '{user_response}', "
                f"not the required literal '{CONFIRMATION_TOKEN}'."
            ),
        }
        log_action(pending, user_response, outcome, technician)
        return outcome

    fn = _ACTIONS[pending.action_name]
    try:
        result = fn(pending.site_id, pending.argument)
        outcome = {
            "executed": True,
            "action": pending.action_name,
            "site_id": pending.site_id,
            "result": result,
        }
    except RouterAPIError as e:
        outcome = {
            "executed": False,
            "reason": f"Action was confirmed but failed when executed: {e}",
        }
    log_action(pending, user_response, outcome, technician)
    return outcome
