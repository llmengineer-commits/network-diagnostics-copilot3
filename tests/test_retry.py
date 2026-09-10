"""Tests for the self-correction (retry + fallback) wrapper."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.retry import call_with_self_correction, summarize_for_agent
from agent.tools import RouterAPIError


def test_succeeds_on_first_try_no_retry_needed():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return {"ok": True}

    result = call_with_self_correction(fn, "test call", site_id="cbd", backoff_s=0)
    assert result.succeeded is True
    assert result.attempts == 1
    assert calls["n"] == 1


def test_retries_then_succeeds():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 2:
            raise RouterAPIError("transient failure")
        return {"ok": True}

    result = call_with_self_correction(fn, "test call", site_id="cbd", max_retries=2, backoff_s=0)
    assert result.succeeded is True
    assert result.attempts == 2


def test_exhausts_retries_then_falls_back_to_ping():
    def always_fails():
        raise RouterAPIError("permanent failure")

    with patch("agent.retry.ping_target") as mock_ping:
        mock_ping.invoke.return_value = {"reachable": True, "latency_ms": 3.2}
        result = call_with_self_correction(
            always_fails, "test call", site_id="cbd", max_retries=2, backoff_s=0
        )

    assert result.succeeded is False
    assert result.used_fallback is True
    assert result.fallback_result["reachable"] is True
    mock_ping.invoke.assert_called_once_with({"site_id": "cbd", "target": "gateway"})


def test_fallback_also_fails_reports_broader_connectivity_issue():
    def always_fails():
        raise RouterAPIError("permanent failure")

    with patch("agent.retry.ping_target") as mock_ping:
        mock_ping.invoke.side_effect = RouterAPIError("ping also failed")
        result = call_with_self_correction(
            always_fails, "test call", site_id="cbd", max_retries=1, backoff_s=0
        )

    assert result.succeeded is False
    assert result.used_fallback is True
    assert result.fallback_result is None
    summary = summarize_for_agent("test call", result)
    assert "broader connectivity problem" in summary


def test_summarize_success_message():
    def fn():
        return {"status": "up"}

    result = call_with_self_correction(fn, "PPPoE check", site_id="cbd", backoff_s=0)
    summary = summarize_for_agent("PPPoE check", result)
    assert "succeeded on attempt 1" in summary
