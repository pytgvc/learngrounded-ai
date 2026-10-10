"""Retrieval: TF-IDF vectors built with NumPy (no ChromaDB, no heavy installs).
Also auto-tags every chunk with its most distinctive topic term."""
import math
import re
from collections import Counter

import numpy as np

STOP = set("""a an the and or of to in on for with by is are was were be been it this that
these those as at from into than then so such can will would should may might do does did
not no yes we you they he she i our your their its if else also which who whom what when
where why how there here about over under between through during each both more most
other some any all only own same too very just s t""".split())

# Generic verbs and filler words. They carry little meaning as search terms or
# quiz blanks, so they are ignored everywhere.
GENERIC = set("""describes describe occurs occur produce produces produced release releases
uses use used make makes shows show works work builds build happens happen contains contain
split splits returns return carries carry stores store controls control absorbs absorb reflects
reflect converts convert fixes fix drives drive moves move forms form takes take gives give gain
gains needs need allows allow requires require include includes also has have been being become
becomes given like process processes source part parts type types way ways thing things one two
three four five six seven eight nine ten many much several number total each every most often
typically usually mainly today next remember welcome back lecture""".split())

TOKEN = re.compile(r"[a-z][a-z0-9\-]+")


def tokenize(text):
    return [w for w in TOKEN.findall(text.lower())
            if w not in STOP and w not in GENERIC and len(w) > 2]


class Index:
    """Holds one TF-IDF matrix over every chunk in the knowledge base."""

    def __init__(self, chunks):
        self.chunks = chunks
        docs = [tokenize(c["text"]) for c in chunks]
        self.vocab = {}
        df = Counter()
        for toks in docs:
            for t in set(toks):
                df[t] += 1
                self.vocab.setdefault(t, len(self.vocab))
        n = max(len(chunks), 1)
        self.idf = np.zeros(len(self.vocab))
        for t, i in self.vocab.items():
            self.idf[i] = math.log((1 + n) / (1 + df[t])) + 1
        self.matrix = np.zeros((n, len(self.vocab)))
        for row, toks in enumerate(docs):
            for t, cnt in Counter(toks).items():
                self.matrix[row, self.vocab[t]] = (1 + math.log(cnt)) * self.idf[self.vocab[t]]
        norms = np.linalg.norm(self.matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1
        self.matrix = self.matrix / norms

    def _vec(self, text):
        v = np.zeros(len(self.vocab))
        for t, cnt in Counter(tokenize(text)).items():
            if t in self.vocab:
                v[self.vocab[t]] = (1 + math.log(cnt)) * self.idf[self.vocab[t]]
        n = np.linalg.norm(v)
        return v / n if n else v

    def search(self, query, k=4):
        if not self.chunks:
            return []
        scores = self.matrix @ self._vec(query)
        order = np.argsort(-scores)[:k]
        return [(self.chunks[i], float(scores[i])) for i in order]

    def distinctive_terms(self, row, top=3):
        """Most distinctive terms of a chunk (TF-IDF weight), used as its topic."""
        vec = self.matrix[row]
        idx = np.argsort(-vec)[:top]
        inv = {i: t for t, i in self.vocab.items()}
        return [inv[i] for i in idx if vec[i] > 0]


def tag_topics(chunks, min_link=0.08):
    """Assigns a topic to every chunk that does not have one yet.

    Chunks with a topic already (a PDF chapter heading or a slide title) act as
    anchors. An untagged chunk, such as a lecture caption, inherits the topic of
    the most similar anchor. If nothing is similar enough, it takes its most
    distinctive term."""
    idx = Index(chunks)
    anchors = [j for j, c in enumerate(chunks) if c.get("topic")]
    for row, c in enumerate(chunks):
        if c.get("topic"):
            continue
        best_topic, best = None, min_link
        if anchors:
            sims = idx.matrix @ idx.matrix[row]
            for j in anchors:
                if sims[j] > best:
                    best, best_topic = float(sims[j]), chunks[j]["topic"]
        if not best_topic:
            terms = idx.distinctive_terms(row, top=1)
            best_topic = terms[0].title() if terms else "General"
        c["topic"] = best_topic
    return chunks, idx
