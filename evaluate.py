"""
Evaluation suite — the two rubric-required pieces:

1. Retrieval evaluation: a ground-truth set of (question -> expected
   chunk) pairs, scored with hit-rate and MRR, comparing at least two
   retrieval strategies (vector-only vs hybrid keyword+vector).

2. End-to-end evaluation: for a set of realistic technician questions,
   generate an answer through the full agent pipeline and score it with
   an LLM-as-a-judge pass (relevant / partially relevant / irrelevant).

Ground truth is intentionally small and hand-checked rather than huge and
auto-generated-only — see GROUND_TRUTH below. Extend it as the doc corpus
grows; the scoring code doesn't change.

Run:
    python evaluate.py                  # retrieval eval only (fast, no LLM calls)
    python evaluate.py --end-to-end     # also runs the LLM-as-judge pass (uses GROQ_API_KEY)
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

RESULTS_DIR = Path(__file__).parent / "evals"
RESULTS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Ground truth for retrieval evaluation.
# Each entry: a realistic technician question, and the doc chunk (by source
# file + heading) that should be retrieved to answer it correctly.
# Hand-checked against data/docs/*.md — extend as the corpus grows.
# ---------------------------------------------------------------------------

GROUND_TRUTH = [
    {
        "question": "Why does this PPPoE session keep dropping every few minutes?",
        "expected_source": "mikrotik_pppoe_troubleshooting.md",
        "expected_heading": "PPPoE session drops repeatedly",
    },
    {
        "question": "PPPoE client never establishes a session at all, no PADO response",
        "expected_source": "mikrotik_pppoe_troubleshooting.md",
        "expected_heading": "PPPoE fails to establish at all (no session ever appears)",
    },
    {
        "question": "DHCP lease shows expired but the device is still online and passing traffic",
        "expected_source": "mikrotik_dhcp_troubleshooting.md",
        "expected_heading": 'Lease shows "expired" but the client still appears connected',
    },
    {
        "question": "Client is not getting any IP address from DHCP at all",
        "expected_source": "mikrotik_dhcp_troubleshooting.md",
        "expected_heading": "DHCP client gets no address at all",
    },
    {
        "question": "WAN interface is at full capacity during peak hours, customers complaining of slow speeds",
        "expected_source": "bandwidth_interface_troubleshooting.md",
        "expected_heading": "Link is saturated / customers reporting slow speeds",
    },
    {
        "question": "How do I decide whether to reset a stuck PPPoE session or escalate it?",
        "expected_source": "mikrotik_pppoe_troubleshooting.md",
        "expected_heading": "Remediation",
    },
    {
        "question": "Interface shows rising packet drops but bandwidth usage is well below capacity",
        "expected_source": "bandwidth_interface_troubleshooting.md",
        "expected_heading": "Link is saturated / customers reporting slow speeds",
    },
    {
        "question": "Is it safe to just reset an expired DHCP lease, or could that make things worse?",
        "expected_source": "mikrotik_dhcp_troubleshooting.md",
        "expected_heading": "Remediation",
    },
]


# ---------------------------------------------------------------------------
# End-to-end evaluation question set — realistic technician queries that
# exercise both retrieval and (where relevant) live router tool calls.
# ---------------------------------------------------------------------------

E2E_QUESTIONS = [
    "A customer's PPPoE session for user-jkariuki keeps dropping. What's going on and what should I check?",
    "Check DHCP lease 10.10.2.102 — the customer says their connection just stopped working.",
    "Is ether1-wan saturated right now, or is something else going on?",
    "user-mochieng says their connection is fine now but was down earlier — what would explain that?",
]


# ---------------------------------------------------------------------------
# Retrieval evaluation
# ---------------------------------------------------------------------------

def hit_rate_and_mrr(results_per_query, k=4):
    """
    results_per_query: list of (expected_key, ranked_retrieved_keys) tuples.
    A 'key' is (source, heading). Returns (hit_rate, mrr).
    """
    hits = 0
    reciprocal_ranks = []
    for expected, retrieved in results_per_query:
        rank = None
        for i, key in enumerate(retrieved[:k], start=1):
            if key == expected:
                rank = i
                break
        if rank is not None:
            hits += 1
            reciprocal_ranks.append(1.0 / rank)
        else:
            reciprocal_ranks.append(0.0)
    n = len(results_per_query)
    return hits / n, sum(reciprocal_ranks) / n


def run_vector_search(query, top_k=4):
    from agent.retrieval import search_docs

    hits = search_docs(query, top_k=top_k)
    return [(h["source"], h["heading"]) for h in hits]


def run_hybrid_search(query, top_k=4):
    """
    Hybrid = vector search re-ranked with a simple BM25-style keyword
    overlap score, then merged. Deliberately simple (no extra service
    required) so this stays reproducible without standing up
    Elasticsearch/OpenSearch just for the comparison.
    """
    from agent.retrieval import search_docs

    # over-fetch on the vector side, then re-rank by combining vector
    # score with lexical overlap
    candidates = search_docs(query, top_k=max(top_k * 2, 8))
    query_terms = set(query.lower().split())

    def lexical_score(text):
        text_terms = set(text.lower().split())
        if not query_terms:
            return 0.0
        return len(query_terms & text_terms) / len(query_terms)

    for c in candidates:
        c["hybrid_score"] = 0.6 * c["score"] + 0.4 * lexical_score(c["text"])

    candidates.sort(key=lambda c: c["hybrid_score"], reverse=True)
    return [(c["source"], c["heading"]) for c in candidates[:top_k]]


def evaluate_retrieval():
    print("Running retrieval evaluation (vector-only vs hybrid) ...\n")

    vector_results = []
    hybrid_results = []
    for item in GROUND_TRUTH:
        expected = (item["expected_source"], item["expected_heading"])
        vector_results.append((expected, run_vector_search(item["question"])))
        hybrid_results.append((expected, run_hybrid_search(item["question"])))

    v_hit, v_mrr = hit_rate_and_mrr(vector_results)
    h_hit, h_mrr = hit_rate_and_mrr(hybrid_results)

    print(f"{'Strategy':<20}{'Hit rate':<12}{'MRR':<12}")
    print(f"{'Vector only':<20}{v_hit:<12.3f}{v_mrr:<12.3f}")
    print(f"{'Hybrid (BM25+vec)':<20}{h_hit:<12.3f}{h_mrr:<12.3f}")

    winner = "Hybrid" if h_mrr >= v_mrr else "Vector only"
    print(f"\nBetter strategy on this ground-truth set: {winner}")

    out = {
        "vector_only": {"hit_rate": v_hit, "mrr": v_mrr},
        "hybrid": {"hit_rate": h_hit, "mrr": h_mrr},
        "n_questions": len(GROUND_TRUTH),
    }
    (RESULTS_DIR / "retrieval_eval.json").write_text(json.dumps(out, indent=2))
    print(f"\nSaved to {RESULTS_DIR / 'retrieval_eval.json'}")
    return out


# ---------------------------------------------------------------------------
# End-to-end evaluation (LLM-as-judge)
# ---------------------------------------------------------------------------

JUDGE_PROMPT = """\
You are grading an AI networking support assistant's answer.

Question: {question}

Retrieved documentation context:
{context}

Assistant's answer:
{answer}

Grade the answer as exactly one of: RELEVANT, PARTIALLY_RELEVANT, IRRELEVANT.
- RELEVANT: directly and correctly addresses the question, grounded in the context.
- PARTIALLY_RELEVANT: on-topic but incomplete, vague, or only loosely grounded.
- IRRELEVANT: does not address the question or contradicts the context.

Respond with only the single label, nothing else.
"""


def evaluate_end_to_end():
    if not os.getenv("GROQ_API_KEY"):
        print(
            "GROQ_API_KEY not set — skipping end-to-end evaluation.\n"
            "Set it in .env to run the LLM-as-judge pass."
        )
        return None

    from langchain_groq import ChatGroq

    from agent.retrieval import search_docs
    from run_agent import build_agent

    print("Running end-to-end evaluation (this calls the LLM — may take a minute) ...\n")

    judge = ChatGroq(model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"), temperature=0)
    agent = build_agent()

    verdicts = []
    for question in E2E_QUESTIONS:
        result = agent.invoke({"messages": [{"role": "user", "content": question}]})
        answer = result["messages"][-1].content

        context_hits = search_docs(question, top_k=3)
        context = "\n\n".join(h["text"] for h in context_hits)

        judge_input = JUDGE_PROMPT.format(question=question, context=context, answer=answer)
        verdict = judge.invoke(judge_input).content.strip().upper()
        verdicts.append({"question": question, "answer": answer, "verdict": verdict})
        print(f"[{verdict}] {question}")

    counts = {"RELEVANT": 0, "PARTIALLY_RELEVANT": 0, "IRRELEVANT": 0}
    for v in verdicts:
        counts[v["verdict"]] = counts.get(v["verdict"], 0) + 1
    total = len(verdicts)

    print("\nSummary:")
    for label, count in counts.items():
        print(f"  {label}: {count}/{total} ({count / total:.0%})")

    out = {"verdicts": verdicts, "summary": counts, "n_questions": total}
    (RESULTS_DIR / "e2e_eval.json").write_text(json.dumps(out, indent=2))
    print(f"\nSaved to {RESULTS_DIR / 'e2e_eval.json'}")
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--end-to-end", action="store_true", help="Also run the LLM-as-judge end-to-end evaluation"
    )
    args = parser.parse_args()

    evaluate_retrieval()
    if args.end_to_end:
        print()
        evaluate_end_to_end()
