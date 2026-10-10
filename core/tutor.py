"""Source-grounded tutor. Answers only from retrieved excerpts, cites each one
with its exact page / slide / timestamp, and refuses when the material does
not cover the question. An optional Gemini call can phrase the answer, but
the retrieved excerpts are always shown as the citations."""
import json
import os
import re
import urllib.request

from . import llm
from .retrieval import tokenize

REFUSE_BELOW = 0.12      # cosine similarity below this = not covered by material
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _best_sentences(query, chunk_text, n=2):
    q = set(tokenize(query))
    sents = [s.strip() for s in SENT_SPLIT.split(chunk_text) if len(s.strip()) > 20]
    scored = sorted(sents, key=lambda s: -len(q & set(tokenize(s))))
    picked = [s for s in scored[:n] if q & set(tokenize(s))]
    return picked or sents[:1]


def _gemini_phrase(query, excerpts):
    """Optional: ask Gemini 2.5 Flash to phrase an answer from the excerpts only.
    Activated only when GEMINI_API_KEY is set. Falls back silently on error."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    context = "\n".join(f"[{i+1}] {e['excerpt']}" for i, e in enumerate(excerpts))
    prompt = ("Answer the student's question using ONLY the numbered excerpts. "
              "Cite excerpts as [n]. If the excerpts do not answer it, say so.\n\n"
              f"Excerpts:\n{context}\n\nQuestion: {query}")
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"gemini-2.5-flash:generateContent?key={key}")
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
    try:
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        return None


REFUSE_HI = ("यह विषय आपकी अपलोड की गई सामग्री में नहीं है, इसलिए मैं बाहर की जानकारी से जवाब नहीं दूंगा। "
             "सवाल दोबारा लिखें या वह लेक्चर या अध्याय अपलोड करें जिसमें यह विषय है।")


def answer(index, query, k=3, lang="en", source=None):
    """Returns {status, answer, citations, lang_note}.
    status is 'grounded' or 'refused'. lang is 'en' or 'hi'.
    source limits answers to one uploaded file (None = all files)."""
    if not index:
        hits = []
    elif source:
        hits = [(c, s) for c, s in index.search(query, k=500) if c["source"] == source][:k]
    else:
        hits = index.search(query, k=k)
    hits = [(c, s) for c, s in hits if s >= REFUSE_BELOW]
    if not hits:
        return {
            "status": "refused",
            "answer": REFUSE_HI if lang == "hi" else (
                "This isn't covered in your uploaded material, so I won't answer "
                "from outside knowledge. Try rephrasing, or upload the lecture or "
                "chapter that covers it."),
            "citations": [],
            "lang_note": "",
        }

    citations = []
    for c, score in hits:
        sentences = _best_sentences(query, c["text"])
        citations.append({
            "chunk_id": c["id"], "source": c["source"], "location": c["location"],
            "kind": c["kind"], "topic": c["topic"], "score": round(score, 3),
            "excerpt": " ".join(sentences),
        })

    phrased = _gemini_phrase(query, citations)
    if phrased:
        text = phrased
    else:
        lines = [f"{e['excerpt']} [{i+1}]" for i, e in enumerate(citations[:2])]
        text = " ".join(lines)

    note = ""
    if lang == "hi":
        if llm.available():
            try:
                text = llm.translate_to_hindi(text)
            except llm.LLMError:
                note = "Hindi translation failed right now, so this answer is in English."
        else:
            note = "Hindi answers need GEMINI_API_KEY. This answer is in English."
    return {"status": "grounded", "answer": text, "citations": citations, "lang_note": note}
