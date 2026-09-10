"""
Mock router REST API.

Simulates the subset of a MikroTik/Huawei router's management API that the
Network Diagnostics Copilot needs: PPPoE session status, DHCP lease tables,
interface/bandwidth stats, and the two write actions the agent can propose
(DHCP lease reset, PPPoE session restart).

This exists so the whole project is reviewable without real ISP hardware.
State is in-memory and reseeds on restart. Endpoints are deliberately shaped
like real MikroTik RouterOS REST responses so swapping this for a real
router later is close to a drop-in replacement (see README for the real-
hardware path).

REMOTE TROUBLESHOOTING: each running instance of this app represents one
physical site's router. Run several instances on different ports (or hosts)
to simulate a multi-site ISP, and point config/sites.json at each — see
docker-compose.yml, which runs three seeded sites out of the box. A
technician then diagnoses ANY site from the same agent conversation by
naming it; the agent resolves the site to its base_url via config/sites.py
and calls this same API against a different instance.

Run a single site:
    SITE_PROFILE=cbd PORT=8088 python mock_router/app.py

Env vars:
    SITE_PROFILE  which seed data to load: cbd | westlands | thika_road (default: cbd)
    PORT          port to listen on (default: 8088)
"""

import os
import random
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, request

app = Flask(__name__)

SITE_PROFILE = os.getenv("SITE_PROFILE", "cbd")
PORT = int(os.getenv("PORT", "8088"))

# ---------------------------------------------------------------------------
# In-memory device state — one seed profile per simulated site, so
# different "remote" sites show genuinely different fault scenarios
# rather than identical mock data.
# ---------------------------------------------------------------------------

def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _seed_state(profile: str):
    now = datetime.now(timezone.utc)

    profiles = {
        "cbd": {
            "pppoe_sessions": {
                "user-jkariuki": {
                    "interface": "pppoe-jkariuki",
                    "status": "down",
                    "uptime": "0s",
                    "last_disconnect_reason": "LCP timeout (no keepalive response)",
                    "caller_id": "AA:BB:CC:11:22:33",
                    "address": "10.10.5.14",
                },
                "user-mochieng": {
                    "interface": "pppoe-mochieng",
                    "status": "up",
                    "uptime": "4h12m",
                    "last_disconnect_reason": None,
                    "caller_id": "AA:BB:CC:44:55:66",
                    "address": "10.10.5.22",
                },
            },
            "dhcp_leases": {
                "10.10.2.101": {
                    "mac": "DE:AD:BE:EF:00:01", "hostname": "desk-01",
                    "status": "bound", "expires": (now + timedelta(hours=6)).isoformat(),
                    "server": "dhcp-cbd-a",
                },
                "10.10.2.102": {
                    "mac": "DE:AD:BE:EF:00:02", "hostname": "desk-02",
                    "status": "expired", "expires": (now - timedelta(minutes=15)).isoformat(),
                    "server": "dhcp-cbd-a",
                },
            },
            "interfaces": {
                "ether1-wan": {
                    "status": "running", "rx_bps": 812_400_000, "tx_bps": 240_100_000,
                    "rx_drops": 1204, "tx_drops": 12, "capacity_bps": 1_000_000_000,
                },
                "ether2-lan": {
                    "status": "running", "rx_bps": 45_000_000, "tx_bps": 62_000_000,
                    "rx_drops": 0, "tx_drops": 0, "capacity_bps": 1_000_000_000,
                },
            },
        },
        "westlands": {
            "pppoe_sessions": {
                "user-anjeri": {
                    "interface": "pppoe-anjeri",
                    "status": "up",
                    "uptime": "9h03m",
                    "last_disconnect_reason": None,
                    "caller_id": "AA:BB:CC:77:88:99",
                    "address": "10.20.5.11",
                },
            },
            "dhcp_leases": {
                "10.20.2.50": {
                    "mac": "DE:AD:BE:EF:10:01", "hostname": "reception-pc",
                    "status": "bound", "expires": (now + timedelta(hours=3)).isoformat(),
                    "server": "dhcp-westlands-a",
                },
            },
            "interfaces": {
                "ether1-wan": {
                    # near-saturation scenario, distinct from the CBD site
                    "status": "running", "rx_bps": 980_000_000, "tx_bps": 310_000_000,
                    "rx_drops": 40, "tx_drops": 2, "capacity_bps": 1_000_000_000,
                },
            },
        },
        "thika_road": {
            "pppoe_sessions": {
                "user-omondi": {
                    "interface": "pppoe-omondi",
                    "status": "down",
                    "uptime": "0s",
                    "last_disconnect_reason": "authentication failure: duplicate session detected",
                    "caller_id": "AA:BB:CC:22:33:44",
                    "address": "10.30.5.18",
                },
            },
            "dhcp_leases": {
                "10.30.2.14": {
                    "mac": "DE:AD:BE:EF:20:01", "hostname": "pos-terminal-1",
                    "status": "bound", "expires": (now + timedelta(hours=5)).isoformat(),
                    "server": "dhcp-thika-a",
                },
            },
            "interfaces": {
                "ether1-wan": {
                    # healthy — used to demonstrate a clean diagnosis too
                    "status": "running", "rx_bps": 120_000_000, "tx_bps": 80_000_000,
                    "rx_drops": 0, "tx_drops": 0, "capacity_bps": 1_000_000_000,
                },
            },
        },
    }

    state = profiles.get(profile, profiles["cbd"])
    state = {k: dict(v) for k, v in state.items()}  # shallow copy per key
    state["fault_injection"] = {"next_call_fails": False}
    return state


STATE = _seed_state(SITE_PROFILE)


def _maybe_inject_fault():
    """If fault injection is armed, fail this one call, then disarm."""
    if STATE["fault_injection"]["next_call_fails"]:
        STATE["fault_injection"]["next_call_fails"] = False
        return True
    return False


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------

@app.get("/api/pppoe/sessions")
def list_pppoe_sessions():
    if _maybe_inject_fault():
        return jsonify({"error": "timeout communicating with PPPoE server"}), 504
    return jsonify(STATE["pppoe_sessions"])


@app.get("/api/pppoe/sessions/<user>")
def get_pppoe_session(user):
    if _maybe_inject_fault():
        return jsonify({"error": "timeout communicating with PPPoE server"}), 504
    session = STATE["pppoe_sessions"].get(user)
    if not session:
        return jsonify({"error": f"no session for user '{user}'"}), 404
    return jsonify(session)


@app.get("/api/dhcp/leases")
def list_dhcp_leases():
    if _maybe_inject_fault():
        return jsonify({"error": "timeout communicating with DHCP server"}), 504
    return jsonify(STATE["dhcp_leases"])


@app.get("/api/dhcp/leases/<ip>")
def get_dhcp_lease(ip):
    if _maybe_inject_fault():
        return jsonify({"error": "timeout communicating with DHCP server"}), 504
    lease = STATE["dhcp_leases"].get(ip)
    if not lease:
        return jsonify({"error": f"no lease for {ip}"}), 404
    return jsonify(lease)


@app.get("/api/interfaces")
def list_interfaces():
    if _maybe_inject_fault():
        return jsonify({"error": "timeout reading interface stats"}), 504
    return jsonify(STATE["interfaces"])


@app.get("/api/interfaces/<name>")
def get_interface(name):
    if _maybe_inject_fault():
        return jsonify({"error": "timeout reading interface stats"}), 504
    iface = STATE["interfaces"].get(name)
    if not iface:
        return jsonify({"error": f"no interface '{name}'"}), 404
    return jsonify(iface)


@app.get("/api/ping/<target>")
def ping(target):
    """Cheap reachability check — used as the self-correction fallback tool."""
    # deterministic-ish: gateway-like targets succeed, everything else has
    # a small chance of failing, so the fallback path is exercisable
    reachable = "gateway" in target or random.random() > 0.15
    return jsonify(
        {
            "target": target,
            "reachable": reachable,
            "latency_ms": round(random.uniform(1.5, 8.0), 2) if reachable else None,
            "checked_at": _now_iso(),
        }
    )


# ---------------------------------------------------------------------------
# Write endpoints — everything the agent's confirmation gate protects
# ---------------------------------------------------------------------------

@app.post("/api/dhcp/leases/<ip>/reset")
def reset_dhcp_lease(ip):
    if _maybe_inject_fault():
        return jsonify({"error": "timeout communicating with DHCP server"}), 504
    lease = STATE["dhcp_leases"].get(ip)
    if not lease:
        return jsonify({"error": f"no lease for {ip}"}), 404
    lease["status"] = "bound"
    lease["expires"] = (datetime.utcnow() + timedelta(hours=6)).isoformat() + "Z"
    return jsonify({"result": "reset", "ip": ip, "lease": lease})


@app.post("/api/pppoe/sessions/<user>/restart")
def restart_pppoe_session(user):
    if _maybe_inject_fault():
        return jsonify({"error": "timeout communicating with PPPoE server"}), 504
    session = STATE["pppoe_sessions"].get(user)
    if not session:
        return jsonify({"error": f"no session for user '{user}'"}), 404
    session["status"] = "up"
    session["uptime"] = "0s"
    session["last_disconnect_reason"] = None
    return jsonify({"result": "restarted", "user": user, "session": session})


# ---------------------------------------------------------------------------
# Test helper — lets evaluate.py / demos deliberately trigger a failure so
# the self-correction retry+fallback path in agent/retry.py is exercised.
# ---------------------------------------------------------------------------

@app.post("/api/_test/arm_fault")
def arm_fault():
    STATE["fault_injection"]["next_call_fails"] = True
    return jsonify({"armed": True})


@app.post("/api/_test/reset_state")
def reset_state():
    global STATE
    STATE = _seed_state(SITE_PROFILE)
    return jsonify({"reset": True, "profile": SITE_PROFILE})


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "site_profile": SITE_PROFILE, "time": _now_iso()})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
