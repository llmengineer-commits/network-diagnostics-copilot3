"""
Network Diagnostics Copilot — CLI entry point.

Wires together:
  - retrieval over vendor docs, filterable by manufacturer (agent/retrieval.py)
  - read-only router tools across one or more remote sites (agent/tools.py)
  - self-correction retry+fallback around every router call (agent/retry.py)
  - a deterministic, audit-logged human-in-the-loop confirmation gate for
    any state-changing action (agent/confirmation.py, agent/audit_log.py)
  - threat intelligence: live CVE lookups and general web search for
    problems outside the local doc corpus (agent/threat_intel.py)

The agent itself only ever sees the tools in AGENT_TOOLS below. It cannot
call reset_dhcp_lease_raw / restart_pppoe_session_raw directly — those
only exist behind execute_with_confirmation. When the agent wants to
propose a write action, it emits a structured proposal (see
`propose_write_action` tool below) which this script intercepts, shows to
the user, and only executes on a literal "YES".

Run:
    python run_agent.py
"""

import getpass
import os
import sys

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.tools import tool

from agent.confirmation import execute_with_confirmation, propose_action
from agent.retrieval import search_vendor_docs
from agent.retry import call_with_self_correction, summarize_for_agent
from agent.threat_intel import check_security_advisories, web_search_troubleshooting
from agent.tools import (
    get_dhcp_lease,
    get_interface_stats,
    get_pppoe_session,
    list_sites,
    ping_target,
)

load_dotenv()

SYSTEM_PROMPT = """\
You are a Network Diagnostics Copilot for ISP support technicians,
supporting multiple remote sites (branches/POPs) from one conversation.

You help diagnose PPPoE, DHCP, and bandwidth/interface issues by, in
order of preference:
1. Searching vendor documentation (search_vendor_docs) for relevant
   troubleshooting guidance. Pass vendor='mikrotik' or vendor='huawei'
   if the technician has said which hardware is involved.
2. Checking live router state at the relevant site (check_pppoe_session,
   check_dhcp_lease, check_interface, ping_target) when the question
   needs current data, not just documentation.
3. Checking security advisories (check_security_advisories) when the
   symptom could plausibly be attack-related (unexpected traffic spikes,
   unfamiliar sessions, repeated auth failures) or when the technician
   asks about vulnerabilities.
4. As a last resort, web_search_troubleshooting for problems not covered
   by the above — a very recent firmware bug, a vendor forum workaround.
   Flag results from this tool as unverified, since they aren't from the
   curated documentation.

Combine whichever of the above you used into a grounded answer that
cites which documentation section, live data point, advisory, or web
result supports your conclusion.

Every router tool requires a site_id (e.g. 'cbd', 'westlands',
'thika_road'). If the technician doesn't say which site they mean, call
list_sites and ask before proceeding — do not guess which remote site a
report applies to.

If the diagnosis calls for a state-changing fix (resetting a DHCP lease,
restarting a PPPoE session), you do NOT have a tool that performs this
directly. Instead, call propose_write_action with the action name, site
ID, target, and your reasoning. The system will show this proposal to
the technician and only execute it if they explicitly confirm. Never
claim an action has been taken unless a tool result confirms it — you
have no ability to change router state except through
propose_write_action.

Be concise and specific. Cite what you relied on. If live data
contradicts what you'd expect from documentation alone, say so
explicitly.
"""


# ---------------------------------------------------------------------------
# Self-correcting wrappers around the read tools, so retry+fallback
# happens transparently every time the agent calls one of these.
# ---------------------------------------------------------------------------

@tool
def check_pppoe_session(site_id: str, username: str) -> str:
    """Check a subscriber's PPPoE session status at a given site, with
    automatic retry and fallback to a same-site gateway ping if the
    router doesn't respond."""
    outcome = call_with_self_correction(
        lambda: get_pppoe_session.invoke({"site_id": site_id, "username": username}),
        description=f"check PPPoE session for {username} at site {site_id}",
        site_id=site_id,
    )
    return summarize_for_agent(f"PPPoE session check for {username} at {site_id}", outcome)


@tool
def check_dhcp_lease(site_id: str, ip: str) -> str:
    """Check a DHCP lease by IP at a given site, with automatic retry
    and fallback to a same-site gateway ping if the router doesn't
    respond."""
    outcome = call_with_self_correction(
        lambda: get_dhcp_lease.invoke({"site_id": site_id, "ip": ip}),
        description=f"check DHCP lease for {ip} at site {site_id}",
        site_id=site_id,
    )
    return summarize_for_agent(f"DHCP lease check for {ip} at {site_id}", outcome)


@tool
def check_interface(site_id: str, interface_name: str) -> str:
    """Check interface throughput/drop stats at a given site, with
    automatic retry and fallback to a same-site gateway ping if the
    router doesn't respond."""
    outcome = call_with_self_correction(
        lambda: get_interface_stats.invoke({"site_id": site_id, "interface_name": interface_name}),
        description=f"check interface stats for {interface_name} at site {site_id}",
        site_id=site_id,
    )
    return summarize_for_agent(f"Interface check for {interface_name} at {site_id}", outcome)


@tool
def propose_write_action(action_name: str, site_id: str, target: str, reason: str) -> str:
    """
    Propose a state-changing action (action_name must be
    'reset_dhcp_lease' or 'restart_pppoe_session') at a given site.
    target is the IP (for a lease reset) or username (for a session
    restart). reason is your diagnostic justification. This does NOT
    execute the action — it only prepares a confirmation prompt that
    will be shown to the technician. You will be told separately whether
    it was confirmed.
    """
    try:
        pending = propose_action(action_name, site_id, target, reason)
    except ValueError as e:
        return f"Could not propose action: {e}"
    # stash it for the CLI loop to pick up and confirm with the user
    LAST_PROPOSAL["pending"] = pending
    return (
        "Proposal recorded. The technician will be asked to confirm "
        "before anything executes. Do not assume it has been done."
    )


LAST_PROPOSAL = {"pending": None}

AGENT_TOOLS = [
    search_vendor_docs,
    list_sites,
    check_pppoe_session,
    check_dhcp_lease,
    check_interface,
    ping_target,
    check_security_advisories,
    web_search_troubleshooting,
    propose_write_action,
]


def build_agent():
    from langchain_groq import ChatGroq

    llm = ChatGroq(
        model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        temperature=0,
        api_key=os.getenv("GROQ_API_KEY"),
    )
    # LangChain 1.x agent API: create_agent replaces the older
    # create_tool_calling_agent + AgentExecutor pattern. It returns a
    # LangGraph-backed agent invoked with {"messages": [...]}.
    return create_agent(model=llm, tools=AGENT_TOOLS, system_prompt=SYSTEM_PROMPT)


def run_cli():
    if not os.getenv("GROQ_API_KEY"):
        print(
            "GROQ_API_KEY not set. Copy .env.example to .env and fill it in.\n"
            "(See README for provider alternatives.)"
        )
        sys.exit(1)

    technician = os.getenv("TECHNICIAN_ID") or getpass.getuser()
    agent = build_agent()
    messages = []
    print("Network Diagnostics Copilot — type 'quit' to exit.\n")

    while True:
        user_input = input("technician> ").strip()
        if user_input.lower() in {"quit", "exit"}:
            break
        if not user_input:
            continue

        LAST_PROPOSAL["pending"] = None
        messages.append({"role": "user", "content": user_input})
        result = agent.invoke({"messages": messages})
        messages = result["messages"]
        reply = messages[-1].content
        print(f"\ncopilot> {reply}\n")

        pending = LAST_PROPOSAL["pending"]
        if pending is not None:
            print(pending.confirmation_prompt())
            confirmation = input("technician (confirm)> ").strip()
            outcome = execute_with_confirmation(pending, confirmation, technician=technician)
            if outcome["executed"]:
                print(f"\n✅ Executed: {outcome}\n")
            else:
                print(f"\n❌ Not executed: {outcome['reason']}\n")
            # let the agent know the outcome so it doesn't assume success
            messages.append(
                {
                    "role": "user",
                    "content": f"[system: confirmation result] {outcome}",
                }
            )


if __name__ == "__main__":
    run_cli()
