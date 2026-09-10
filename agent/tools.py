"""
Tool definitions the agent can call: retrieval over vendor docs, and
read/write access to router APIs across one or more remote sites.

REMOTE TROUBLESHOOTING: every router call takes a site_id. This is what
lets a single conversation diagnose "the CBD site" and "the Westlands
site" without the technician needing to know each site's address,
credentials, or connection details — that's resolved once, centrally, in
config/sites.py. Adding a new physical location means adding one entry
to the site registry, not touching any tool code.

Read tools (get_pppoe_session, get_dhcp_lease, get_interface_stats, ping)
are safe to call freely. Write tools (reset_dhcp_lease,
restart_pppoe_session) are NOT called directly by the agent — they are
wrapped by the confirmation gate in confirmation.py, which is the only
thing allowed to invoke them. See run_agent.py for how the two are wired
together.
"""

import os

import requests
from langchain_core.tools import tool

from config.sites import get_site, list_site_ids

REQUEST_TIMEOUT_S = float(os.getenv("ROUTER_TIMEOUT_S", "5"))


class RouterAPIError(Exception):
    """Raised when a router API call fails (timeout, 5xx, connection error, unknown site)."""


def _headers_for(site_id: str) -> dict:
    site = get_site(site_id)
    if site.api_token:
        return {"Authorization": f"Bearer {site.api_token}"}
    return {}


def _get(site_id: str, path: str):
    try:
        site = get_site(site_id)
    except ValueError as e:
        raise RouterAPIError(str(e)) from e
    try:
        resp = requests.get(
            f"{site.base_url}{path}", headers=_headers_for(site_id), timeout=REQUEST_TIMEOUT_S
        )
    except requests.RequestException as e:
        raise RouterAPIError(f"connection error calling site '{site_id}' {path}: {e}") from e
    if resp.status_code >= 400:
        raise RouterAPIError(f"site '{site_id}' {path} returned {resp.status_code}: {resp.text}")
    return resp.json()


def _post(site_id: str, path: str):
    try:
        site = get_site(site_id)
    except ValueError as e:
        raise RouterAPIError(str(e)) from e
    try:
        resp = requests.post(
            f"{site.base_url}{path}", headers=_headers_for(site_id), timeout=REQUEST_TIMEOUT_S
        )
    except requests.RequestException as e:
        raise RouterAPIError(f"connection error calling site '{site_id}' {path}: {e}") from e
    if resp.status_code >= 400:
        raise RouterAPIError(f"site '{site_id}' {path} returned {resp.status_code}: {resp.text}")
    return resp.json()


# ---------------------------------------------------------------------------
# Read tools — safe, no confirmation needed
# ---------------------------------------------------------------------------

@tool
def list_sites() -> str:
    """
    List the ISP sites (physical locations / POPs) this copilot can
    remotely diagnose. Call this first if the technician hasn't said
    which site they mean, or if you're unsure a site_id is valid.
    """
    ids = list_site_ids()
    lines = []
    for sid in ids:
        site = get_site(sid)
        lines.append(f"- {site.id}: {site.name}")
    return "\n".join(lines) if lines else "No sites configured."


@tool
def get_pppoe_session(site_id: str, username: str) -> dict:
    """
    Look up the current status of a subscriber's PPPoE session by
    username, e.g. 'user-jkariuki', at a given site (e.g. 'cbd',
    'westlands', 'thika_road'). Call list_sites first if you don't know
    the valid site_id. Returns status, uptime, and the last disconnect
    reason if the session is currently down.
    """
    return _get(site_id, f"/api/pppoe/sessions/{username}")


@tool
def get_dhcp_lease(site_id: str, ip: str) -> dict:
    """
    Look up a DHCP lease by IP address, e.g. '10.10.2.102', at a given
    site. Returns lease status (bound/expired), MAC, hostname, and
    expiry time.
    """
    return _get(site_id, f"/api/dhcp/leases/{ip}")


@tool
def get_interface_stats(site_id: str, interface_name: str) -> dict:
    """
    Get current throughput and drop statistics for a router interface,
    e.g. 'ether1-wan', at a given site. Returns rx/tx bps, rx/tx drops,
    and capacity.
    """
    return _get(site_id, f"/api/interfaces/{interface_name}")


@tool
def ping_target(site_id: str, target: str) -> dict:
    """
    From a given site's router, ping a target (e.g. 'gateway' or an IP)
    to check basic reachability. Use this as a fallback diagnostic when
    a more specific router API call fails or times out, to at least
    confirm the site's device is reachable at all before escalating.
    """
    return _get(site_id, f"/api/ping/{target}")


# ---------------------------------------------------------------------------
# Write tools — state-changing, gated behind human confirmation.
# These are intentionally NOT decorated with @tool and are not exposed
# directly to the agent's tool list. confirmation.py imports and calls
# these functions only after receiving an explicit "YES" from the user.
# ---------------------------------------------------------------------------

def reset_dhcp_lease_raw(site_id: str, ip: str) -> dict:
    """Reset (clear) a DHCP lease at a given site so the client can re-request an address."""
    return _post(site_id, f"/api/dhcp/leases/{ip}/reset")


def restart_pppoe_session_raw(site_id: str, username: str) -> dict:
    """Restart a subscriber's PPPoE session at a given site."""
    return _post(site_id, f"/api/pppoe/sessions/{username}/restart")


READ_TOOLS = [list_sites, get_pppoe_session, get_dhcp_lease, get_interface_stats, ping_target]
