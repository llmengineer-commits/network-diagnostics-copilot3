"""
Tests for the human-in-the-loop confirmation gate. This is the
safety-critical component of the project, so it gets the most thorough
coverage: every way a confirmation could be "close but not exact" must
be rejected, and audit logging must fire regardless of outcome.
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from agent.confirmation import PendingAction, execute_with_confirmation, propose_action
from agent.tools import RouterAPIError


def make_pending():
    return PendingAction(
        action_name="reset_dhcp_lease",
        site_id="cbd",
        argument="10.10.2.102",
        reason="test reason",
    )


def test_propose_action_rejects_unknown_action():
    with pytest.raises(ValueError):
        propose_action("delete_everything", "cbd", "x", "no")


def test_propose_action_builds_pending_correctly():
    pending = propose_action("reset_dhcp_lease", "cbd", "10.10.2.102", "reason text")
    assert pending.action_name == "reset_dhcp_lease"
    assert pending.site_id == "cbd"
    assert pending.argument == "10.10.2.102"


@pytest.mark.parametrize(
    "bad_response",
    ["yes", "Yes", "YES ", " YES", "yes please", "y", "confirm", "", "sure", "ok"],
)
def test_execute_rejects_anything_but_exact_literal_yes(bad_response):
    pending = make_pending()
    with patch("agent.confirmation.log_action"):
        outcome = execute_with_confirmation(pending, bad_response)
    assert outcome["executed"] is False
    assert "cancelled" in outcome["reason"].lower()


def test_execute_accepts_exact_literal_yes_and_calls_the_action():
    pending = make_pending()
    with patch.dict(
        "agent.confirmation._ACTIONS",
        {"reset_dhcp_lease": lambda site_id, arg: {"ip": arg, "site_id": site_id, "result": "reset"}},
    ), patch("agent.confirmation.log_action"):
        outcome = execute_with_confirmation(pending, "YES")
    assert outcome["executed"] is True
    assert outcome["result"]["ip"] == "10.10.2.102"


def test_execute_handles_router_failure_after_confirmation():
    pending = make_pending()

    def failing_action(site_id, arg):
        raise RouterAPIError("simulated failure")

    with patch.dict("agent.confirmation._ACTIONS", {"reset_dhcp_lease": failing_action}), \
         patch("agent.confirmation.log_action"):
        outcome = execute_with_confirmation(pending, "YES")
    assert outcome["executed"] is False
    assert "failed when executed" in outcome["reason"]


def test_every_confirmation_attempt_is_audit_logged():
    pending = make_pending()
    with patch("agent.confirmation.log_action") as mock_log:
        execute_with_confirmation(pending, "no thanks")
    mock_log.assert_called_once()
    args = mock_log.call_args[0]
    assert args[0] is pending
    assert args[1] == "no thanks"
