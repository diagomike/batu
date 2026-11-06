"""Hybrid retrieval: BM25 keyword search over English and translated text,
plus Gemini embeddings when an API key is set. Results are merged with
reciprocal rank fusion. Everything is kept in memory and in one small file.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from collections import Counter

import numpy as np

from .. import content
from . import corpus
from .llm import Gemini

VEC_PATH = content.ROOT / "var" / "vectors.npz"
TOKEN = re.compile(r"[\w']+", re.UNICODE)
STOP = set("""a an the and or of to in on at for with is are was be by it this that from as your you can i my me we our how what get much many
when where which who do does need get have has will not if any about into than then there these those its it's
fi kan ni akka keessa irratti waliin ta'e jedhu""".split())


TYPE_WEIGHT = {"service": 1.4, "help": 1.2, "fact": 1.15, "emergency": 1.2, "place": 1.05, "office": 1.0,
               "news": 0.9, "notice": 0.75, "tender": 0.85, "vacancy": 0.85, "project": 0.95, "event": 1.0}


def tokens(text: str) -> list[str]:
    out = []
    for t in TOKEN.findall(text.lower()):
        t = t.strip("'")
        if len(t) < 2 or t in STOP:
            continue
        if len(t) > 4 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]  # simple English plural
        out.append(t)
        if len(t) > 6:
            out.append("~" + t[:6])  # crude stem: helps Afaan Oromoo suffixes and English plurals
    return out


class Index:
    def __init__(self):
        self.lock = threading.Lock()
        self.docs: list[dict] = []
        self.tf: list[Counter] = []
        self.df: Counter = Counter()
        self.lens: list[int] = []
        self.avg = 1.0
        self.vectors = None
        self.gemini = Gemini()
        self.version = ""

    def _doc_text_all(self, d):
        parts = [d["title"], d["text"]]
        for lang in ("om", "am"):
            parts += [x for x in (content.tr(p, lang) for p in d.get("pieces", [])) if x not in d.get("pieces", [])]
        return "\n".join(parts)

    def build(self, use_embeddings: bool = True):
        docs = corpus.documents()
        tf, df, lens = [], Counter(), []
        for d in docs:
            c = Counter(tokens(self._doc_text_all(d)))
            tf.append(c)
            df.update(c.keys())
            lens.append(sum(c.values()))
        version = hashlib.sha1(json.dumps([(d["id"], d["text"]) for d in docs]).encode()).hexdigest()[:12]
        vectors = None
        if use_embeddings and self.gemini.enabled:
            vectors = self._load_vectors(version)
            if vectors is None:
                try:
                    vectors = np.array(self.gemini.embed([f"{d['title']}\n{d['text']}" for d in docs]), dtype=np.float32)
                    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-9
                    VEC_PATH.parent.mkdir(parents=True, exist_ok=True)
                    np.savez(VEC_PATH, v=vectors, version=version)
                except Exception as e:  # noqa: BLE001
                    print("[rag] embeddings unavailable, keyword search only:", e)
                    vectors = None
        with self.lock:
            self.docs, self.tf, self.df, self.lens = docs, tf, df, lens
            self.avg = sum(lens) / max(len(lens), 1)
            self.vectors = vectors
            self.version = version
        return len(docs)

    def _load_vectors(self, version):
        if VEC_PATH.exists():
            z = np.load(VEC_PATH)
            if str(z["version"]) == version:
                return z["v"]
        return None

    def bm25(self, query: str, k=12):
        q = tokens(query)
        n = len(self.docs)
        scores = []
        for i, c in enumerate(self.tf):
            s = 0.0
            for t in q:
                if t not in c:
                    continue
                idf = math.log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5))
                f = c[t]
                w = 0.5 if t.startswith("~") else 1.0
                s += w * idf * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * self.lens[i] / self.avg))
            if s > 0:
                # Prefer how-to pages over short dated items when scores are close.
                s *= TYPE_WEIGHT.get(self.docs[i]["type"], 1.0)
                if any(t in tokens(self.docs[i]["title"]) for t in q):
                    s *= 1.25
                scores.append((s, i))
        scores.sort(reverse=True)
        return scores[:k]

    def dense(self, query: str, k=12):
        if self.vectors is None:
            return []
        try:
            qv = np.array(self.gemini.embed([query], task="RETRIEVAL_QUERY")[0], dtype=np.float32)
        except Exception as e:  # noqa: BLE001
            print("[rag] query embedding failed:", e)
            return []
        qv /= np.linalg.norm(qv) + 1e-9
        sims = self.vectors @ qv
        top = np.argsort(-sims)[:k]
        return [(float(sims[i]), int(i)) for i in top if sims[i] > 0.35]

    def search(self, query: str, k=6):
        with self.lock:
            kw = self.bm25(query)
            dn = self.dense(query)
            fused: dict[int, float] = {}
            for rank, (_, i) in enumerate(kw):
                fused[i] = fused.get(i, 0) + 1 / (60 + rank)
            for rank, (_, i) in enumerate(dn):
                fused[i] = fused.get(i, 0) + 1 / (60 + rank)
            order = sorted(fused, key=lambda i: -fused[i])[:k]
            best_kw = kw[0][0] if kw else 0.0
            return [self.docs[i] for i in order], {"keyword_top": best_kw, "dense": bool(dn)}


INDEX = Index()
