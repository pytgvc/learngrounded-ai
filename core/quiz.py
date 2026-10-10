"""Adaptive assessment: generates MCQ, short-answer and numerical questions
from the uploaded material. Each question carries a topic, a source location and
a difficulty. Answers are verified before a question is kept, and questions a
student has already seen are never repeated."""
import hashlib
import json
import random
import re

from . import learner
from .retrieval import tokenize
from .store import connect

SENT = re.compile(r"(?<=[.!?])\s+")
NUM = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w.])")


def _sentences(text):
    """Complete sentences of usable length. Headings and fragments are skipped."""
    out = []
    for s in SENT.split(text):
        s = s.strip()
        if 50 <= len(s) <= 240 and s.endswith((".", "!", "?")):
            out.append(s)
    return out


def _key_terms(index, tokens):
    """Content words worth blanking out, rarest (most specific) first."""
    terms = {t for t in tokens if t in index.vocab and len(t) >= 5}
    return sorted(terms, key=lambda t: -index.idf[index.vocab[t]])


def distractor_pool(index, chunks):
    """Key terms from the whole material. Wrong options are drawn from here,
    so distractors are real course vocabulary rather than random words."""
    pool = []
    for c in chunks:
        for s in _sentences(c["text"]):
            pool.extend(_key_terms(index, tokenize(s)))
    return list(dict.fromkeys(pool))


def _difficulty(term, numeric=False):
    if numeric:
        return "hard"
    return "easy" if len(term) <= 5 else "medium" if len(term) <= 8 else "hard"


def _fp(qtype, prompt, answer):
    return hashlib.sha1(f"{qtype}|{prompt}|{answer}".encode()).hexdigest()


def _attempted_ids():
    with connect() as con:
        return {r["question_id"] for r in con.execute("SELECT question_id FROM attempts")}


def generate(index, chunks, topics=None, n=5, qtypes=("mcq", "short", "numerical"),
             seed=None):
    """Builds up to n verified questions for the chosen topics (None = all)."""
    rng = random.Random(seed)
    pool = [c for c in chunks if not topics or c["topic"] in topics]
    rng.shuffle(pool)
    made, used_terms = [], set()
    attempted = _attempted_ids()
    types_cycle = list(qtypes)
    distractors = distractor_pool(index, pool)

    for chunk in pool:
        for sent in _sentences(chunk["text"]):
            if len(made) >= n:
                break
            qtype = types_cycle[len(made) % len(types_cycle)]
            tokens = tokenize(sent)
            if not tokens:
                continue
            q = None
            if qtype == "mcq":
                q = _make_mcq(index, chunk, sent, tokens, used_terms, rng, distractors)
            elif qtype == "numerical":
                q = _make_numerical(chunk, sent, rng)
            else:
                q = _make_short(index, chunk, sent, tokens, used_terms)
            if q and q["verified"]:
                made.append(q)
                used_terms.add(q["answer"].lower())
        if len(made) >= n:
            break

    saved = []
    with connect() as con:
        for q in made:
            fp = _fp(q["qtype"], q["prompt"], q["answer"])
            con.execute(
                "INSERT OR IGNORE INTO questions(qtype,prompt,options,answer,explanation,"
                "topic,source,location,chunk_id,difficulty,fingerprint,verified)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (q["qtype"], q["prompt"], _json(q["options"]), q["answer"], q["explanation"],
                 q["topic"], q["source"], q["location"], q["chunk_id"], q["difficulty"],
                 fp, 1))
            row = con.execute("SELECT * FROM questions WHERE fingerprint=?", (fp,)).fetchone()
            d = dict(row)
            if d["id"] not in attempted:
                d["options"] = q["options"]
                saved.append(d)
    return saved[:n]


def _json(obj):
    return json.dumps(obj)


def _make_mcq(index, chunk, sent, tokens, used, rng, distractors):
    cands = [t for t in _key_terms(index, tokens) if t not in used]
    if not cands:
        return None
    key = cands[0]
    stem = re.sub(rf"\b{re.escape(key)}\b", "_____", sent, count=1, flags=re.I)
    if "_____" not in stem:
        return None
    # cross-check: the blanked stem should retrieve its own source chunk
    top = index.search(stem.replace("_____", ""), k=1)
    if not top or top[0][0]["id"] != chunk["id"]:
        return None
    options_pool = [t for t in distractors
                    if t not in tokens and t != key and key not in t and t not in used]
    rng.shuffle(options_pool)
    wrong = options_pool[:3]
    if len(wrong) < 3:
        return None
    options = wrong + [key]
    rng.shuffle(options)
    letters = ["A", "B", "C", "D"]
    return {
        "qtype": "mcq",
        "prompt": f"Fill in the blank: {stem}",
        "options": [f"{letters[i]}. {o}" for i, o in enumerate(options)],
        "answer": key,
        "explanation": f"The material says: \"{sent}\"",
        "topic": chunk["topic"], "source": chunk["source"], "location": chunk["location"],
        "chunk_id": chunk["id"], "difficulty": _difficulty(key),
        "verified": not any(w in sent.lower() for w in wrong),
    }


def _make_numerical(chunk, sent, rng):
    m = NUM.search(sent)
    if not m:
        return None
    val = m.group(1)
    stem = sent[:m.start()] + "_____" + sent[m.end():]
    try:
        x = float(val)
    except ValueError:
        return None
    alts = {round(x * 1.5, 2), round(x * 0.5, 2), round(x + 3, 2), round(max(x - 2, 0), 2)}
    alts.discard(x)
    alts = [str(int(a)) if a == int(a) else str(a) for a in alts]
    wrong = [a for a in alts if a != val][:3]
    if len(wrong) < 3:
        return None
    options = wrong + [val]
    rng.shuffle(options)
    letters = ["A", "B", "C", "D"]
    return {
        "qtype": "numerical",
        "prompt": f"Fill in the missing number: {stem}",
        "options": [f"{letters[i]}. {o}" for i, o in enumerate(options)],
        "answer": val,
        "explanation": f"The material says: \"{sent}\"",
        "topic": chunk["topic"], "source": chunk["source"], "location": chunk["location"],
        "chunk_id": chunk["id"], "difficulty": _difficulty(val, numeric=True),
        "verified": float(val) == x,
    }


def _make_short(index, chunk, sent, tokens, used):
    cands = [t for t in _key_terms(index, tokens) if t not in used]
    if not cands:
        return None
    key = cands[0]
    prompt = f"In your own words, explain what the material says about {key}."
    return {
        "qtype": "short",
        "prompt": prompt,
        "options": None,
        "answer": sent,
        "explanation": f"Reference: \"{sent}\"",
        "topic": chunk["topic"], "source": chunk["source"], "location": chunk["location"],
        "chunk_id": chunk["id"], "difficulty": _difficulty(key),
        "verified": key in sent.lower(),
    }


def grade(question, given):
    """Returns (correct, feedback). Short answers are graded by key-term coverage."""
    if question["qtype"] in ("mcq", "numerical"):
        letter_ans = None
        options = question["options"] if isinstance(question["options"], list) \
            else json.loads(question["options"] or "[]")
        for o in options:
            if o.startswith(given + ". "):
                letter_ans = o.split(". ", 1)[1]
        correct = letter_ans is not None and letter_ans.strip().lower() == question["answer"].strip().lower()
        verdict = "Correct." if correct else f"Not quite. The answer is \"{question['answer']}\"."
    else:
        ref = set(tokenize(question["answer"]))
        got = set(tokenize(given or ""))
        cover = len(ref & got) / max(len(ref), 1)
        correct = cover >= 0.35
        verdict = ("Good, you covered the key ideas." if correct
                   else "Partly there. Re-read the cited section and try again.")
    feedback = f"{verdict} {question['explanation']} (Source: {question['source']}, {question['location']})"
    return correct, feedback


def record_attempt(question, given, mode="quiz"):
    correct, feedback = grade(question, given)
    with connect() as con:
        import time
        con.execute("INSERT INTO attempts(question_id,topic,correct,given,mode,ts)"
                    " VALUES(?,?,?,?,?,?)",
                    (question["id"], question["topic"], 1 if correct else 0, given, mode,
                     time.time()))
    mastery = learner.update(question["topic"], correct)
    return {"correct": correct, "feedback": feedback, "mastery": mastery,
            "topic": question["topic"]}


def apply_diagnostic_priors(results):
    """New student: set starting mastery per topic from the diagnostic quiz."""
    by_topic = {}
    for r in results:
        by_topic.setdefault(r["topic"], []).append(r["correct"])
    for topic, marks in by_topic.items():
        acc = sum(marks) / len(marks)
        learner.set_prior(topic, round(0.1 + 0.75 * acc, 3))
    return by_topic
