"""
Threat intelligence and general web-search tools.

Two distinct capabilities, kept separate because they answer different
questions:

1. check_security_advisories — queries the NVD (National Vulnerability
   Database) CVE API for known, catalogued vulnerabilities affecting a
   vendor/product. This is authoritative, structured data — appropriate
   when the technician (or the agent, reasoning about a symptom like
   repeated auth failures or unfamiliar sessions) needs to know "is this
   a known CVE" rather than "what does the internet currently think."
   Public API, no key required for the request volume this project needs.
   https://nvd.nist.gov/developers/vulnerabilities

2. web_search_troubleshooting — a general web search for problems that
   aren't in the local vendor doc corpus and aren't a catalogued CVE
   (e.g. a very new firmware bug, a vendor forum workaround, breaking
   news about an active campaign). Implemented via the `ddgs` package
   (no API key required), which is convenient for a portfolio project
   but is a best-effort scrape rather than a paid search API's SLA —
   see the docstring on that function for the production-swap note.

Both are read-only. Neither can change router state.
"""

import os

import requests
from langchain_core.tools import tool

NVD_API_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
NVD_API_KEY = os.getenv("NVD_API_KEY")  # optional — raises the rate limit, not required
REQUEST_TIMEOUT_S = 10


@tool
def check_security_advisories(vendor_keyword: str) -> str:
    """
    Search the NVD (National Vulnerability Database) for recent CVEs
    matching a vendor/product keyword, e.g. 'MikroTik RouterOS' or
    'Huawei router'. Use this when a symptom could plausibly be
    attack-related (unexpected traffic spikes, unfamiliar PPPoE
    sessions, repeated authentication failures) or when the technician
    directly asks about vulnerabilities. Returns up to 5 recent matching
    CVEs with severity and a short description.
    """
    params = {"keywordSearch": vendor_keyword, "resultsPerPage": 5}
    headers = {"apiKey": NVD_API_KEY} if NVD_API_KEY else {}
    try:
        resp = requests.get(NVD_API_URL, params=params, headers=headers, timeout=REQUEST_TIMEOUT_S)
    except requests.RequestException as e:
        return f"Could not reach the NVD CVE database: {e}"

    if resp.status_code == 429:
        return (
            "NVD API rate limit hit. Set NVD_API_KEY in .env for a higher rate limit "
            "(free — https://nvd.nist.gov/developers/request-an-api-key), or retry shortly."
        )
    if resp.status_code >= 400:
        return f"NVD API returned {resp.status_code}: {resp.text[:200]}"

    data = resp.json()
    vulns = data.get("vulnerabilities", [])
    if not vulns:
        return f"No CVEs found matching '{vendor_keyword}' in the NVD database."

    lines = [f"Found {len(vulns)} recent CVE(s) matching '{vendor_keyword}':"]
    for item in vulns:
        cve = item.get("cve", {})
        cve_id = cve.get("id", "UNKNOWN")
        descriptions = cve.get("descriptions", [])
        desc = next((d["value"] for d in descriptions if d.get("lang") == "en"), "No description.")
        metrics = cve.get("metrics", {})
        severity = "UNKNOWN"
        for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
            if key in metrics and metrics[key]:
                severity = metrics[key][0].get("cvssData", {}).get("baseSeverity", "UNKNOWN")
                break
        lines.append(f"\n[{cve_id}] severity={severity}\n{desc[:300]}")
    return "\n".join(lines)


@tool
def web_search_troubleshooting(query: str) -> str:
    """
    Search the web for networking troubleshooting information not
    covered by the local vendor documentation or the CVE database — for
    example a very recent firmware issue, a vendor forum workaround, or
    breaking news about an active attack campaign. Use this as a last
    resort after search_vendor_docs and check_security_advisories have
    both failed to give a satisfying answer, since the local
    documentation is curated and citable while this is not.
    """
    try:
        from ddgs import DDGS
    except ImportError:
        return (
            "Web search is unavailable: the 'ddgs' package is not installed. "
            "Run `pip install ddgs` to enable this tool, or swap this function for a "
            "paid search API (Tavily, SerpAPI, Bing) for production reliability — "
            "see the docstring in agent/threat_intel.py."
        )

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
    except Exception as e:  # noqa: BLE001 — this is a best-effort external scrape
        return f"Web search failed: {e}. This tool uses a free, unofficial search backend " \
               f"and can be rate-limited or unavailable; consider a paid search API for " \
               f"production use."

    if not results:
        return f"No web results found for '{query}'."

    lines = [f"Web search results for '{query}' (verify against official sources before acting):"]
    for r in results:
        title = r.get("title", "")
        body = r.get("body", "")
        href = r.get("href", "")
        lines.append(f"\n- {title}\n  {body[:250]}\n  {href}")
    return "\n".join(lines)
