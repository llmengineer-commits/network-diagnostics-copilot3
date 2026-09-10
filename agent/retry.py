"""
Self-correction wrapper for router tool calls.

Real network hardware fails for mundane reasons: a timeout, a transient
auth hiccup, a device mid-reboot. This is even more true for remote
sites, where the failure could be the WAN path to that site rather than
the site's router itself. The rubric this project targets calls for the
agent to retry and fall back to a secondary tool (e.g. pinging the
gateway) on tool error/timeout before admitting defeat — this module is
that behavior, factored out so it wraps ANY router call rather than
being duplicated per-tool.

Behavior:
    1. Call the tool. If it succeeds, return the result.
    2. On failure, retry up to `max_retries` times with a short backoff.
    3. If still failing, fall back to a secondary diagnostic (ping the
       gateway AT THE SAME SITE) so the agent can at least report
       something useful ("the DHCP server didn't respond, but the site's
       router is reachable") rather than a bare failure.
    4. If the fallback also fails, report a clear, final failure — the
       agent should not retry forever or fail silently.
"""

import time
from dataclasses import dataclass, field
from typing import Callable

from agent.tools import RouterAPIError, ping_target


@dataclass
class SelfCorrectionResult:
    succeeded: bool
    result: dict | None = None
    attempts: int = 0
    used_fallback: bool = False
    fallback_result: dict | None = None
    error: str | None = None
    log: list[str] = field(default_factory=list)


def call_with_self_correction(
    fn: Callable[[], dict],
    description: str,
    site_id: str,
    max_retries: int = 2,
    backoff_s: float = 0.5,
    fallback_target: str = "gateway",
) -> SelfCorrectionResult:
    """
    Run `fn` (a zero-arg callable that performs one router API call) with
    retry + fallback. `description` is a short human-readable label for
    logging. `site_id` is the site `fn` was calling — the fallback ping
    targets the SAME site, so a failure at a remote site doesn't get
    "explained away" by successfully pinging a different site's router.
    """
    log = []
    attempts = 0
    last_error = None

    for attempt in range(1, max_retries + 2):  # first try + max_retries
        attempts = attempt
        try:
            result = fn()
            log.append(f"attempt {attempt}: succeeded")
            return SelfCorrectionResult(
                succeeded=True, result=result, attempts=attempts, log=log
            )
        except RouterAPIError as e:
            last_error = str(e)
            log.append(f"attempt {attempt}: failed ({last_error})")
            if attempt <= max_retries:
                time.sleep(backoff_s)

    # all retries exhausted — fall back to a cheap reachability check
    # at the same site, rather than surfacing a bare failure
    log.append(
        f"all {attempts} attempts failed for '{description}' at site '{site_id}'; "
        f"falling back to ping"
    )
    try:
        fallback = ping_target.invoke({"site_id": site_id, "target": fallback_target})
        log.append(f"fallback ping to '{fallback_target}' at site '{site_id}': {fallback}")
        return SelfCorrectionResult(
            succeeded=False,
            attempts=attempts,
            used_fallback=True,
            fallback_result=fallback,
            error=last_error,
            log=log,
        )
    except RouterAPIError as e:
        log.append(f"fallback ping also failed: {e}")
        return SelfCorrectionResult(
            succeeded=False,
            attempts=attempts,
            used_fallback=True,
            fallback_result=None,
            error=f"{last_error}; fallback ping also failed: {e}",
            log=log,
        )


def summarize_for_agent(description: str, outcome: SelfCorrectionResult) -> str:
    """Turn a SelfCorrectionResult into a short string the agent can reason over."""
    if outcome.succeeded:
        return f"'{description}' succeeded on attempt {outcome.attempts}: {outcome.result}"

    if outcome.used_fallback and outcome.fallback_result and outcome.fallback_result.get("reachable"):
        return (
            f"'{description}' failed after {outcome.attempts} attempt(s) ({outcome.error}). "
            f"Fallback reachability check to the gateway succeeded "
            f"(latency {outcome.fallback_result.get('latency_ms')}ms), so the site's router "
            f"itself is up — the specific service being queried is the likely problem, not "
            f"basic connectivity to that site."
        )
    return (
        f"'{description}' failed after {outcome.attempts} attempt(s) ({outcome.error}), "
        f"and the fallback reachability check also failed. This suggests a broader "
        f"connectivity problem to that site, not just the specific service queried."
    )
