"""Learner model: per-topic mastery using Bayesian Knowledge Tracing (BKT).
Updates after every quiz answer and tutor exchange. New students start from a
diagnostic quiz that sets their starting estimates."""
import time

from .store import connect

P_INIT = 0.20       # prior: chance the student already knows a topic
P_TRANSIT = 0.15    # chance of learning it after one exposure
P_SLIP = 0.10       # knows it but answers wrong
P_GUESS = 0.25      # doesn't know it but answers right (4-option MCQ-ish)


def _row(topic):
    with connect() as con:
        r = con.execute("SELECT * FROM mastery WHERE topic=?", (topic,)).fetchone()
        return dict(r) if r else None


def get_mastery(topic):
    r = _row(topic)
    return r["p_known"] if r else P_INIT


def set_prior(topic, p):
    with connect() as con:
        con.execute("INSERT OR REPLACE INTO mastery(topic,p_known,attempts,correct,last_seen)"
                    " VALUES(?,?,COALESCE((SELECT attempts FROM mastery WHERE topic=?),0),"
                    "COALESCE((SELECT correct FROM mastery WHERE topic=?),0),?)",
                    (topic, p, topic, topic, time.time()))


def update(topic, correct):
    """One BKT step for a graded answer. Returns the new mastery estimate."""
    p = get_mastery(topic)
    if correct:
        post = p * (1 - P_SLIP) / (p * (1 - P_SLIP) + (1 - p) * P_GUESS)
    else:
        post = p * P_SLIP / (p * P_SLIP + (1 - p) * (1 - P_GUESS))
    new = post + (1 - post) * P_TRANSIT
    with connect() as con:
        con.execute("INSERT INTO mastery(topic,p_known,attempts,correct,last_seen)"
                    " VALUES(?,?,1,?,?) ON CONFLICT(topic) DO UPDATE SET"
                    " p_known=excluded.p_known, attempts=attempts+1,"
                    " correct=correct+excluded.correct, last_seen=excluded.last_seen",
                    (topic, new, 1 if correct else 0, time.time()))
    return round(new, 3)


def exposure(topic):
    """Tutor conversation about a topic: a small learning step, no grading."""
    p = get_mastery(topic)
    new = p + (1 - p) * (P_TRANSIT / 2)
    with connect() as con:
        con.execute("INSERT INTO mastery(topic,p_known,attempts,correct,last_seen)"
                    " VALUES(?,?,0,0,?) ON CONFLICT(topic) DO UPDATE SET"
                    " p_known=excluded.p_known, last_seen=excluded.last_seen",
                    (topic, new, time.time()))
    return round(new, 3)


def all_mastery():
    with connect() as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM mastery ORDER BY p_known")]
    return rows


def weak_topics(threshold=0.5, limit=5):
    return [r for r in all_mastery() if r["p_known"] < threshold][:limit]


def report():
    """Post-assessment report: weak topics, likely misconceptions, where to revisit."""
    with connect() as con:
        wrong = con.execute(
            "SELECT a.topic, a.given, q.answer, q.source, q.location, q.prompt"
            " FROM attempts a JOIN questions q ON q.id=a.question_id"
            " WHERE a.correct=0 AND a.given IS NOT NULL ORDER BY a.id DESC LIMIT 30"
        ).fetchall()
    misconceptions = []
    seen = set()
    for w in wrong:
        key = (w["topic"], w["given"], w["answer"])
        if key in seen or not w["given"]:
            continue
        seen.add(key)
        misconceptions.append({
            "topic": w["topic"],
            "text": f"Chose \"{w['given']}\" when the material says \"{w['answer']}\"",
            "revisit": f"{w['source']}, {w['location']}",
        })
    return {"weak_topics": weak_topics(), "misconceptions": misconceptions[:6]}
