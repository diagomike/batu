"""Hybrid retrieval: BM25 keyword search over English and translated text,
plus Gemini embeddings of every record in English, Afaan Oromoo and Amharic
when an API key is set (cached per text in data/vectors.npz, kept in git). Results are merged with
reciprocal rank fusion. Everything is kept in memory and in one small file.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from collections import Counter

import numpy as np

from .. import content
from . import corpus
from .llm import Gemini

VEC_PATH = content.ROOT / "data" / "vectors.npz"
VEC_LANGS = ("en", "om", "am")  # every record is embedded in each language
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

    def localized(self, d, lang: str) -> str:
        """The record in one language, using the site's own translations (English when missing)."""
        if lang == "en":
            return d["title"] + "\n" + d["text"]
        return "\n".join(content.tr(p, lang) for p in d.get("pieces", []))

    def build(self, use_embeddings: bool = True):
        docs = corpus.documents()
        tf, df, lens = [], Counter(), []
        for d in docs:
            c = Counter(tokens(self._doc_text_all(d)))
            tf.append(c)
            df.update(c.keys())
            lens.append(sum(c.values()))
        texts = {lang: [self.localized(d, lang) for d in docs] for lang in VEC_LANGS}
        if use_embeddings and self.gemini.enabled:
            try:
                self.gemini.pick_models()
            except Exception as e:  # noqa: BLE001
                print("[rag] could not list Gemini models:", e)
        version = hashlib.sha1(json.dumps([texts, self.gemini.embed_model or ""]).encode()).hexdigest()[:12]
        vectors = None
        if use_embeddings and self.gemini.enabled:
            vectors = self._embed_cached([t for lang in VEC_LANGS for t in texts[lang]])
            if vectors is not None:
                vectors = vectors.reshape(len(VEC_LANGS), len(docs), -1)  # [language, doc, dim]
        with self.lock:
            self.docs, self.tf, self.df, self.lens = docs, tf, df, lens
            self.avg = sum(lens) / max(len(lens), 1)
            self.vectors = vectors
            self.version = version
        return len(docs)

    def _embed_cached(self, flat: list[str]):
        """Vectors for every text, embedding only texts not in the cache.

        The cache (data/vectors.npz, kept in git) is keyed by model + text, so an edit
        re-embeds just the changed records and a fresh server starts with no API calls.
        Texts that cannot be embedded (quota) get a zero vector and rely on keywords.
        """
        model = self.gemini.embed_model or ""
        keys = [hashlib.sha1(f"{model}|{t}".encode()).hexdigest()[:16] for t in flat]
        cache: dict[str, np.ndarray] = {}
        if VEC_PATH.exists():
            try:
                z = np.load(VEC_PATH)
                if "keys" in z:
                    cache = dict(zip(z["keys"].tolist(), z["v"]))
            except Exception as e:  # noqa: BLE001
                print("[rag] vector cache unreadable, rebuilding:", e)
        missing = [i for i, k in enumerate(keys) if k not in cache]
        if missing:
            print(f"[rag] embedding {len(missing)} new or changed texts ({len(flat) - len(missing)} cached)")
            for start in range(0, len(missing), 50):
                chunk = missing[start:start + 50]
                vecs = None
                for attempt in range(3):
                    try:
                        vecs = self.gemini.embed([flat[i] for i in chunk])
                        break
                    except Exception as e:  # noqa: BLE001
                        if "429" in str(e) and attempt < 2:
                            time.sleep(30 * (attempt + 1))  # free tier: per-minute limit
                            continue
                        print("[rag] embeddings unavailable for some texts, keywords cover them:", str(e)[:160])
                        break
                if vecs is None:
                    break
                for i, v in zip(chunk, vecs):
                    v = np.asarray(v, dtype=np.float32)
                    cache[keys[i]] = v / (np.linalg.norm(v) + 1e-9)
            used = {k: cache[k] for k in keys if k in cache}
            if used:
                VEC_PATH.parent.mkdir(parents=True, exist_ok=True)
                np.savez(VEC_PATH, keys=np.array(list(used)), v=np.stack(list(used.values())))
        if not any(k in cache for k in keys):
            return None
        dim = len(next(cache[k] for k in keys if k in cache))
        return np.stack([cache.get(k, np.zeros(dim, dtype=np.float32)) for k in keys])

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
        sims = (self.vectors @ qv).max(axis=0)  # best match over the record's three languages
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
