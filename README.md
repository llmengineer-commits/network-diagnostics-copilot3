# Network Diagnostics Copilot

**An agentic AI system that lets ISP support technicians remotely diagnose network faults — PPPoE drops, DHCP failures, bandwidth issues — across multiple sites, in plain language, backed by manufacturer documentation, live router data, and current threat intelligence — with a human confirmation gate and full audit trail before any action that changes network state.**

[Demo video](#demo) · [Architecture](#architecture) · [Evaluation results](#evaluation) · [Run it yourself](#running-the-project)

---

## Table of contents

- [The problem](#the-problem)
- [Who this is for](#who-this-is-for)
- [What it does](#what-it-does)
- [Demo](#demo)
- [Architecture](#architecture)
- [Manufacturer documentation](#manufacturer-documentation)
- [Retrieval](#retrieval)
- [Remote troubleshooting: multi-site](#remote-troubleshooting-multi-site)
- [Threat intelligence](#threat-intelligence)
- [Safety: human-in-the-loop confirmation](#safety-human-in-the-loop-confirmation)
- [Audit trail](#audit-trail)
- [Resilience: self-correction](#resilience-self-correction)
- [Evaluation](#evaluation)
- [Testing](#testing)
- [Tech stack](#tech-stack)
- [Running the project](#running-the-project)
- [Running with Docker](#running-with-docker)
- [Project structure](#project-structure)
- [Design decisions and trade-offs](#design-decisions-and-trade-offs)
- [Limitations and future work](#limitations-and-future-work)
- [About](#about)

---

## The problem

ISPs with more than one site — branches, POPs, client premises — run support desks where technicians spend most of their time on the same handful of fault categories: a subscriber's PPPoE session keeps dropping, a DHCP lease won't renew, a link is saturated and nobody's sure why. The fix usually lives in one of three places: a vendor manual (MikroTik or Huawei documentation, hundreds of pages, inconsistently indexed), the router itself (which the technician has to remotely connect to and interrogate), or — increasingly — a very recent vendor advisory or CVE that isn't in any manual yet.

Generic LLM chatbots don't help here. They don't have the vendor documentation, they can't see any router, and they don't know today's vulnerability feed. A technician asking ChatGPT "why does this PPPoE session keep dropping" gets generic advice, not an answer grounded in the actual device state at the actual site.

This project closes that gap: an agent that reads manufacturer documentation, queries live routers across multiple remote sites, checks current threat intelligence, and can act on what it finds — with a hard confirmation gate and an audit trail before anything changes.

## Who this is for

Built from direct exposure to this exact workflow while gaining ISP experience at The Hague Internet Services (Nairobi), under supervisor David Maina. The primary user is a Tier-1/Tier-2 ISP support technician who needs a faster path from "customer at site X reports a problem" to "root cause identified and (optionally) fixed" — without waiting on a senior engineer for every ticket, and without needing to remember which of several sites' routers has which address. It's also the first service in a planned line of AI-assisted networking tools for DEVCO.IO, the IT company built around software development, hardware repair, connectivity, and physical security.

## What it does

Given a natural-language question or a support ticket naming a site, the agent:

1. Retrieves the relevant manufacturer documentation for the symptom described — filterable by vendor (MikroTik, Huawei) if the hardware is known.
2. If the question needs live data, calls the named site's router REST API — checking PPPoE session status, DHCP lease tables, or interface throughput — rather than guessing from documentation alone.
3. If the symptom could be attack-related, checks live CVE feeds for known vulnerabilities, and can fall back to a general web search for very recent issues not yet in any manual or database.
4. Combines all of the above into a grounded, cited answer explaining the likely cause.
5. If the fix requires a state-changing action (e.g. resetting a DHCP lease), the agent proposes the action and **waits for an explicit "YES"** before executing it. Nothing destructive happens without a human in the loop, and every proposal — confirmed, rejected, or failed — is written to an append-only audit log.
6. If a tool call fails or times out, the agent retries and falls back to a secondary diagnostic at the same site (e.g. pinging that site's gateway) before reporting failure — it doesn't just give up on the first error, and it doesn't "fix" a remote-site failure by checking a different site.

## Demo

*[Insert a 60–90 second screen recording here: a technician asks about a site by name → agent checks live data at that site → checks a CVE feed → proposes a DHCP lease reset → waits for "YES" → executes → the audit log shows the record. A recording is worth more to a reviewer than any amount of README text — put it first.]*

## Architecture

```
                         ┌─────────────────────┐
                         │   CLI (run_agent.py) │
                         │  technician's chat   │
                         └──────────┬───────────┘
                                    │
                         ┌──────────▼───────────┐
                         │  LangChain Agent      │
                         │  (create_agent,       │
                         │   LangChain 1.x)      │
                         └──┬─────┬─────┬────┬───┘
                            │     │     │    │
         ┌──────────────────┘     │     │    └───────────────────┐
         │                        │     │                        │
┌────────▼─────────┐  ┌───────────▼───┐ │              ┌─────────▼──────────┐
│  RAG retrieval     │  │ Multi-site    │ │              │  Threat intel       │
│  (local Qdrant,     │  │ router tools  │ │              │  (NVD CVE API +     │
│   vendor-tagged)    │  │ (site_id-based)│ │             │   web search        │
└────────┬────────────┘  └───────┬───────┘ │              │   fallback)         │
         │                        │         │              └─────────────────────┘
┌────────▼────────────┐  ┌────────▼────────▼──────┐
│  Ingestion            │  │  Self-correction         │
│  mikrotik/huawei/      │  │  (retry + same-site      │
│  general docs          │  │   fallback ping)         │
└────────────────────────┘  └──────────┬───────────────┘
                                        │
                         ┌──────────────▼───────────────┐
                         │  Confirmation gate             │
                         │  (waits for literal "YES")     │
                         └──────────────┬───────────────┘
                                        │
                         ┌──────────────▼───────────────┐
                         │  Audit log (audit_log.jsonl)   │
                         └────────────────────────────────┘
                                        │
                    ┌───────────────────┼───────────────────┐
                    │                   │                   │
            ┌───────▼──────┐   ┌────────▼───────┐  ┌────────▼───────┐
            │ Router: CBD   │   │ Router:         │  │ Router:         │
            │ (mock/real)   │   │ Westlands        │  │ Thika Road       │
            └───────────────┘   └──────────────────┘  └──────────────────┘
```

The design separates concerns that are easy to conflate in a RAG project: *knowing* (retrieval over documentation and threat feeds) and *doing* (tool-calling into a live, specific, remote system). Keeping them as distinct paths through the agent — rather than one undifferentiated "context" blob — is what makes the confirmation gate possible: the agent can only trigger it on the *doing* path, never on a retrieval-only answer, and only ever against the one site the technician named.

## Manufacturer documentation

The knowledge base is organized by manufacturer under `data/docs/`:

- `data/docs/mikrotik/` — RouterOS-flavored PPPoE and DHCP troubleshooting
- `data/docs/huawei/` — VRP-flavored PPPoE and DHCP notes (different CLI, same underlying protocols)
- `data/docs/general/` — vendor-agnostic content (bandwidth/interface troubleshooting applies across hardware)

The subfolder name becomes a `vendor` tag carried through ingestion into the vector store, so `search_vendor_docs` can be scoped to a manufacturer when the technician knows which hardware is involved (`vendor='mikrotik'`) or left open to search everything. Adding a third manufacturer (e.g. Cisco, Ubiquiti) means adding a subfolder and running `ingest.py` again — no code changes.

> **Note on the sample doc corpus.** The content in `data/docs/` is representative material written for this project, since real vendor manuals are proprietary. Swap in your own licensed documentation — `ingest.py` only assumes markdown files with `##`/`###` section headings inside a vendor-named subfolder.

## Retrieval

Documents are embedded locally (`sentence-transformers`, `all-MiniLM-L6-v2` — no API key required) and indexed in Qdrant running in embedded/local mode (on-disk, no server or Docker needed — a deliberate choice given 8GB-RAM development environments). Two retrieval strategies are evaluated head-to-head — see [Evaluation](#evaluation): vector-only search, and a hybrid approach that re-ranks vector candidates with lexical overlap, since exact terminology (interface names, error codes) often matters as much as semantic meaning for technical documentation.

## Remote troubleshooting: multi-site

Real ISP support covers more than one physical location. `config/sites.py` is a site registry — three sites ship configured out of the box (`cbd`, `westlands`, `thika_road`), each pointing at its own router base URL. Every router tool (`check_pppoe_session`, `check_dhcp_lease`, `check_interface`, `ping_target`, and the write actions) takes a `site_id`, so a single conversation can diagnose "the CBD site" and then "the Westlands site" without the technician needing to know either site's address or credentials — that's resolved once, centrally, in the registry.

Adding a real remote site is a config change, not a code change: add an entry to `config/sites.py` (or point `SITES_CONFIG` at a JSON file) with its base URL and the name of an environment variable holding its API token — credentials are never stored in the registry file itself.

The three sites ship with genuinely different seeded scenarios — CBD has a PPPoE session down on an LCP timeout, Westlands has a near-saturated WAN link, Thika Road has a PPPoE session down on a duplicate-session auth failure — so remote troubleshooting is demonstrable, not just structurally present.

## Threat intelligence

Two tools, for two different questions:

- **`check_security_advisories`** queries the [NVD (National Vulnerability Database) CVE API](https://nvd.nist.gov/developers/vulnerabilities) for catalogued vulnerabilities matching a vendor/product keyword. Authoritative, structured, free (an optional API key raises the rate limit). The agent reaches for this when a symptom could plausibly be attack-related — unexpected traffic spikes, unfamiliar sessions, repeated auth failures — or when the technician asks directly.
- **`web_search_troubleshooting`** is a general web-search fallback (via the `ddgs` package, no API key) for problems that are too recent for either the local docs or the CVE database — a brand-new firmware bug, a vendor forum workaround. It's a last resort, and results are explicitly flagged as unverified in the agent's answer, since they aren't from curated documentation. Swap this for a paid search API (Tavily, SerpAPI, Bing) for production reliability — see the docstring in `agent/threat_intel.py`.

## Safety: human-in-the-loop confirmation

Any tool call that changes router state (a DHCP lease reset, a PPPoE session restart) at any site is gated behind a deterministic confirmation step: the agent states exactly what it intends to do, at which site, and why, then waits for the technician to type a literal **"YES"** before executing. This isn't a soft prompt-engineered suggestion — it's enforced in code (`agent/confirmation.py`), so there's no path from "diagnosis" to "action" that skips the human. 28 unit tests cover this specifically, including every near-miss confirmation string ("yes", "Yes", "yes please", "y", "confirm", "ok"...) to verify only the exact literal is ever accepted.

## Audit trail

Every call to the confirmation gate — confirmed, rejected, or confirmed-but-failed-on-execution — is appended to `audit_log.jsonl` (`agent/audit_log.py`) with a timestamp, the technician, the site, the action, the stated reason, and the outcome. This is the kind of trail any organization should expect before trusting an agent with write access to production infrastructure, and it exists independent of whether the action actually executed — a rejected proposal is just as much a record as an executed one.

## Resilience: self-correction

Tool calls against real network hardware fail for mundane reasons — a timeout, a transient auth error, a device that's mid-reboot — and remote sites add a failure mode of their own: the WAN path *to* the site, not just the site's router. Rather than surfacing the raw failure, the agent retries the call, and on continued failure falls back to pinging the *same site's* gateway (never a different site's) to at least confirm basic reachability before reporting that it couldn't complete the check. The goal is for the agent to behave the way a competent junior engineer would: try again, try something adjacent, then escalate — not fail silently or fail loud on the first hiccup, and not "explain away" a remote outage by successfully reaching somewhere else.

## Evaluation

Two separate questions are evaluated, because "the agent found relevant documents" and "the agent gave a good answer" are not the same claim.

**Retrieval evaluation.** A hand-checked ground-truth set of 8 question → expected-chunk pairs (`evaluate.py:GROUND_TRUTH`) is scored against two retrieval strategies:

| Strategy | Hit rate | MRR |
|---|---|---|
| Vector search only | *[run `python evaluate.py`]* | *[run `python evaluate.py`]* |
| Hybrid (vector + lexical overlap re-rank) | *[run `python evaluate.py`]* | *[run `python evaluate.py`]* |

Run `python evaluate.py` and paste the printed numbers here — it also writes `evals/retrieval_eval.json`. Extend `GROUND_TRUTH` as the doc corpus grows; the scoring code doesn't change.

**End-to-end evaluation.** Generated answers are scored with an LLM-as-a-judge pass against the retrieved context — relevant / partially relevant / irrelevant — reported as a percentage.

| Metric | Result |
|---|---|
| % answers judged relevant | *[run `python evaluate.py --end-to-end`]* |
| % answers judged partially relevant | *[run `python evaluate.py --end-to-end`]* |
| % answers judged irrelevant | *[run `python evaluate.py --end-to-end`]* |

## Testing

28 unit tests (`pytest tests/`) cover the safety-critical and correctness-critical logic: the confirmation gate (every near-miss confirmation string is rejected; every attempt is audit-logged), self-correction (retry counts, same-site fallback, both-fail reporting), the site registry (unknown sites raise, tokens resolve from environment), and ingestion (vendor tagging, and a regression test pinning down a real heading-mislabeling bug found during development). CI (`.github/workflows/ci.yml`) runs the full suite plus a compile check on every push.

```bash
pytest tests/ -v
```

## Tech stack

| Layer | Choice |
|---|---|
| Orchestration | Python, LangChain (`create_agent`, LangChain 1.x) |
| LLM | Groq (`llama-3.3-70b-versatile`, free tier) |
| Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`, local, no API key) |
| Vector storage | Qdrant, embedded/local mode (on-disk, no server) |
| Multi-site router access | Flask mocks (`mock_router/app.py`) behind a site registry (`config/sites.py`) — swap for real REST clients per site |
| Threat intelligence | NVD CVE API (live) + `ddgs` web search fallback |
| Audit logging | JSON Lines, append-only (`agent/audit_log.py`) |
| Testing | pytest (28 tests), GitHub Actions CI |
| Deployment | Docker + docker-compose (3 router sites + agent) |
| Frontend | CLI (`run_agent.py`) |

## Running the project

> A reviewer will not have access to real ISP hardware. This project ships **mocked routers** for three sites (a small Flask service returning realistic MikroTik/Huawei-style responses, one instance per site) as the default path, so the full pipeline — ingestion through agent response, across multiple sites — runs end to end without any physical device.

```bash
# 1. Clone and enter the project
git clone https://github.com/llmengineer-commits/network-diagnostics-copilot.git
cd network-diagnostics-copilot

# 2. Set up the environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Configure environment variables
cp .env.example .env
# fill in GROQ_API_KEY (free tier: https://console.groq.com)
# everything else has a working default

# 4. Start the three mock site routers, each in its own terminal
SITE_PROFILE=cbd PORT=8088 python mock_router/app.py
SITE_PROFILE=westlands PORT=8089 python mock_router/app.py
SITE_PROFILE=thika_road PORT=8090 python mock_router/app.py

# 5. In another terminal, run ingestion (chunks + embeds + indexes the vendor docs)
python ingest.py

# 6. Run the agent
python run_agent.py
# try: "list the sites you can see"
# try: "check the PPPoE session for user-jkariuki at cbd"
# try: "is there anything I should know about MikroTik RouterOS vulnerabilities?"

# 7. Run the test suite and the evaluation suite
pytest tests/ -v
python evaluate.py                 # retrieval evaluation (fast, no LLM calls)
python evaluate.py --end-to-end    # also runs the LLM-as-judge pass (needs GROQ_API_KEY)
```

To try the safety gate and self-correction paths directly against a site's mock router:

```bash
curl -X POST http://localhost:8088/api/_test/arm_fault    # next call to this site fails
curl -X POST http://localhost:8088/api/_test/reset_state  # reset that site to seed data
```

## Running with Docker

The same multi-site setup, in one command:

```bash
cp .env.example .env    # fill in GROQ_API_KEY
docker compose up --build
```

This starts all three site routers plus the agent (`docker-compose.yml`), wired together automatically — the agent container talks to the router containers by service name, not `localhost`.

## Project structure

```
network-diagnostics-copilot/
├── ingest.py                    # chunk + embed + index vendor docs into local Qdrant
├── run_agent.py                 # CLI entry point for the LangChain agent
├── evaluate.py                  # retrieval + end-to-end evaluation suite
├── requirements.txt
├── .env.example
├── Dockerfile                   # agent image
├── Dockerfile.router            # mock router image (parameterized by SITE_PROFILE)
├── docker-compose.yml           # 3 sites + agent, one command
├── LICENSE
├── config/
│   └── sites.py                  # multi-site registry (remote troubleshooting)
├── mock_router/
│   └── app.py                    # Flask stub simulating a MikroTik/Huawei REST API, one per site
├── agent/
│   ├── tools.py                   # site-aware read/write router tool definitions
│   ├── retrieval.py                # semantic search tool over the vector store, vendor-filterable
│   ├── confirmation.py             # human-in-the-loop gate logic
│   ├── retry.py                     # self-correction / fallback logic
│   ├── threat_intel.py               # CVE lookups + general web search
│   └── audit_log.py                  # append-only log of every confirmed/rejected write action
├── tests/                        # pytest suite (28 tests)
├── .github/workflows/ci.yml      # compile check + pytest on every push
├── evals/                        # evaluation results (retrieval_eval.json, e2e_eval.json)
├── data/docs/
│   ├── mikrotik/                  # RouterOS-flavored docs
│   ├── huawei/                    # VRP-flavored docs
│   └── general/                   # vendor-agnostic docs
├── notebooks/                    # reviewer-friendly walkthrough (planned)
└── README.md
```

## Design decisions and trade-offs

- **Frameworks over from-scratch RAG.** The course teaches RAG without frameworks so the fundamentals are visible; this project uses LangChain because the tool-calling and agent orchestration it provides are what the diagnostic-copilot use case actually needs, not just retrieval.
- **Confirmation as a hard gate, not a prompt.** An LLM can be prompted to "ask before acting," but prompted behavior isn't reliable enough for infrastructure that customers depend on — the gate is implemented in code, not in the system prompt, and is unit-tested against every plausible near-miss confirmation.
- **Site_id as an explicit, required parameter — never inferred.** Every router tool requires the technician (via the agent) to state which site they mean. This was a deliberate choice over "guess from context": a wrong guess against the wrong remote site is a much worse failure mode than asking one clarifying question.
- **Threat intel as two tiers, not one.** The CVE database is authoritative but slow-moving; general web search is fast-moving but unverified. Keeping them as separate tools (rather than one blended "search the internet" tool) lets the agent — and the technician reading its answer — know which kind of evidence they're looking at.
- **Mocked routers by default, multiplied by site.** Real hardware access can't be assumed for reviewers, so mocks are the default path — and running three independently-seeded instances, rather than one, is what makes "remote troubleshooting across sites" reviewable rather than just described.

## Limitations and future work

- Evaluation ground truth currently covers PPPoE, DHCP, and bandwidth faults from the sample corpus; it should grow alongside the documentation as more vendors are added.
- The confirmation gate currently requires an exact "YES" — a future version could support richer confirmation language while keeping the same deterministic safety guarantee.
- `web_search_troubleshooting` uses a free, unofficial search backend suitable for a portfolio project; production use should swap in a paid search API with an SLA.
- Only two manufacturers (MikroTik, Huawei) are represented in the sample corpus; the vendor-tagging design supports adding more without code changes.
- Planned next step: fleet-wide anomaly detection across all configured sites at once, rather than one site per query, plus a mobile/web frontend so technicians aren't tied to a CLI.

## About

Built by Ian Nyaga ([@llmengineer-commits](https://github.com/llmengineer-commits)) as the capstone project for [LLM Zoomcamp 2026](https://github.com/DataTalksClub/llm-zoomcamp), and the first service planned for DEVCO.IO's AI/ML offering.

Contact: iannyaga83@gmail.com
