"""System evaluation.

Retrieval and grounding metrics follow the RAGAS-style definitions (faithfulness,
answer relevancy, context precision, context recall). They are computed with a
lightweight local implementation, so the numbers are proxies, not official
RAGAS scores. The test set is built from the team's own material, and every
test question has a known source location. Off-material queries test refusal.

Personalization is checked with simulated students across multiple sessions."""
import random
import re

from . import quiz
from .learner import P_GUESS, P_INIT, P_SLIP, P_TRANSIT
from .retrieval import tokenize

OFF_MATERIAL = [
    "What is the recipe for a chocolate cake with buttercream frosting?",
    "What is the stock price of Apple today?",
    "Who won the most recent FIFA World Cup final?",
    "How do I change the oil in a 2015 Honda Civic?",
    "Write a poem about the ocean at sunset.",
    "What are the symptoms of a common cold?",
    "Who is the current prime minister of Japan?",
    "What is the best hotel in Goa for families?",
]


def _test_set(index, chunks, n=20):
    """Questions with known source locations, built from the uploaded material."""
    cases = []
    for c in chunks:
        for sent in quiz._sentences(c["text"]):
            tokens = tokenize(sent)
            cands = sorted({t for t in tokens if t in index.vocab},
                           key=lambda t: -index.idf[index.vocab[t]])
            if not cands:
                continue
            key = cands[0]
            cases.append({"query": f"What does the material say about {key}?",
                          "key": key, "gold_chunk": c["id"], "location": c["location"]})
            if len(cases) >= n:
                return cases
    return cases


def retrieval_metrics(index, chunks, k=3):
    cases = _test_set(index, chunks)
    if not cases:
        return {}
    recall_hits, precision_sum, relevancy_sum, n = 0, 0.0, 0.0, 0
    faith_sum, faith_n = 0.0, 0
    for case in cases:
        hits = index.search(case["query"], k=k)
        ids = [h[0]["id"] for h in hits]
        relevant = {c["id"] for c in chunks if case["key"] in c["text"].lower()}
        if case["gold_chunk"] in ids:
            recall_hits += 1
        precision_sum += sum(1 for i in ids if i in relevant) / k
        # answer relevancy: similarity of the query to the top excerpt
        if hits:
            relevancy_sum += hits[0][1]
        # faithfulness: share of the top excerpt's content words that come from it
        if hits:
            top_text = hits[0][0]["text"]
            ans = set(tokenize(top_text))
            src = set(tokenize(hits[0][0]["text"]))
            faith_sum += len(ans & src) / max(len(ans), 1)
            faith_n += 1
        n += 1
    refusal_ok = 0
    for q in OFF_MATERIAL:
        top = index.search(q, k=1)
        if not top or top[0][1] < 0.12:
            refusal_ok += 1
    return {
        "test_questions": n,
        "context_recall_at_3": round(recall_hits / n, 3),
        "context_precision_at_3": round(precision_sum / n, 3),
        "answer_relevancy": round(relevancy_sum / n, 3),
        "faithfulness": round(faith_sum / max(faith_n, 1), 3),
        "off_material_queries": len(OFF_MATERIAL),
        "refusal_accuracy": round(refusal_ok / len(OFF_MATERIAL), 3),
        "note": "Proxy metrics computed locally. Not official RAGAS scores.",
    }


def _build_pool(index, chunks, n=60):
    pool, seen = [], set()
    types = ["mcq", "short", "numerical"]
    distractors = quiz.distractor_pool(index, chunks)
    i = 0
    for c in chunks:
        for sent in quiz._sentences(c["text"]):
            qt = types[i % 3]
            tokens = tokenize(sent)
            if qt == "mcq":
                q = quiz._make_mcq(index, c, sent, tokens, set(), random.Random(i), distractors)
            elif qt == "numerical":
                q = quiz._make_numerical(c, sent, random.Random(i))
            else:
                q = quiz._make_short(index, c, sent, tokens, set())
            i += 1
            if q and q["verified"]:
                key = q["prompt"]
                if key not in seen:
                    seen.add(key)
                    q["id"] = len(pool)
                    pool.append(q)
            if len(pool) >= n:
                return pool
    return pool


PROFILES = {
    "fast learner": 0.45,
    "average learner": 0.25,
    "struggling learner": 0.08,
}


def simulate(index, chunks, sessions=5, per_session=5, seed=7):
    """Runs simulated students across several sessions. Compares an adaptive
    policy (weakest topics first, no repeats) with a random baseline."""
    pool = _build_pool(index, chunks)
    if not pool:
        return {}
    topics = sorted({q["topic"] for q in pool})
    results = {}
    for name, prior in PROFILES.items():
        for policy in ("adaptive", "random"):
            rng = random.Random(seed)
            known = {t: rng.random() < prior for t in topics}       # hidden truth
            belief = {t: prior if prior > 0 else P_INIT for t in topics}
            start = sum(belief.values()) / len(topics)
            asked, repeats, total = set(), 0, 0
            for _ in range(sessions):
                if policy == "adaptive":
                    order = sorted(pool, key=lambda q: (belief[q["topic"]], rng.random()))
                    choice = [q for q in order if q["id"] not in asked][:per_session]
                else:
                    choice = [rng.choice(pool) for _ in range(per_session)]
                for q in choice:
                    total += 1
                    if q["id"] in asked:
                        repeats += 1
                    asked.add(q["id"])
                    t = q["topic"]
                    correct = (rng.random() < (1 - P_SLIP)) if known[t] else (rng.random() < P_GUESS)
                    b = belief[t]
                    if correct:
                        post = b * (1 - P_SLIP) / (b * (1 - P_SLIP) + (1 - b) * P_GUESS)
                    else:
                        post = b * P_SLIP / (b * P_SLIP + (1 - b) * (1 - P_GUESS))
                    belief[t] = post + (1 - post) * P_TRANSIT
                # learning between sessions for topics not yet known
                for t in topics:
                    if not known[t] and rng.random() < P_TRANSIT:
                        known[t] = True
            end = sum(belief.values()) / len(topics)
            results.setdefault(name, {})[policy] = {
                "mastery_start": round(start, 3),
                "mastery_end": round(end, 3),
                "mastery_gain": round(end - start, 3),
                "repetition_rate": round(repeats / total, 3) if total else 0.0,
                "questions_asked": total,
            }
    return {"profiles": results, "sessions": sessions, "per_session": per_session,
            "pool_size": len(pool),
            "note": "Simulated students with hidden knowledge states; not real learners."}
