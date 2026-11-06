"""Minimal Gemini REST client (free tier works for the demo).

Model names change often, so by default we ask the API which models this key
can use and pick a Flash model for answers and an embedding model for search.
Override with GEMINI_MODEL and GEMINI_EMBED_MODEL in .env.
"""
from __future__ import annotations

import json
import os

import httpx

BASE = "https://generativelanguage.googleapis.com/v1beta"


class Gemini:
    def __init__(self, key: str | None = None):
        self.key = key or os.getenv("GEMINI_API_KEY", "").strip()
        self._models: list[dict] | None = None
        self.gen_model = os.getenv("GEMINI_MODEL", "").strip() or None
        self.embed_model = os.getenv("GEMINI_EMBED_MODEL", "").strip() or None

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    def _headers(self):
        return {"x-goog-api-key": self.key, "Content-Type": "application/json"}

    def models(self) -> list[dict]:
        if self._models is None:
            r = httpx.get(f"{BASE}/models", headers=self._headers(), params={"pageSize": 200}, timeout=30)
            r.raise_for_status()
            self._models = r.json().get("models", [])
        return self._models

    def pick_models(self):
        if self.gen_model and self.embed_model:
            return
        names = [(m["name"], m.get("supportedGenerationMethods", [])) for m in self.models()]
        if not self.gen_model:
            flash = [n for n, s in names if "generateContent" in s and "flash" in n and "lite" not in n
                     and not any(x in n for x in ("image", "tts", "audio", "live", "preview", "exp", "thinking"))]
            flash = flash or [n for n, s in names if "generateContent" in s and "flash" in n]
            self.gen_model = sorted(flash)[-1] if flash else "models/gemini-flash-latest"
        if not self.embed_model:
            emb = [n for n, s in names if "embedContent" in s or "batchEmbedContents" in s]
            pref = [n for n in emb if "gemini-embedding" in n] or emb
            self.embed_model = sorted(pref)[-1] if pref else "models/gemini-embedding-001"

    def embed(self, texts: list[str], task: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
        self.pick_models()
        out: list[list[float]] = []
        for i in range(0, len(texts), 50):
            batch = texts[i:i + 50]
            body = {"requests": [{"model": self.embed_model, "content": {"parts": [{"text": t[:6000]}]}, "taskType": task}
                                 for t in batch]}
            r = httpx.post(f"{BASE}/{self.embed_model}:batchEmbedContents", headers=self._headers(), json=body, timeout=120)
            r.raise_for_status()
            out.extend(e["values"] for e in r.json()["embeddings"])
        return out

    def generate_json(self, system: str, prompt: str) -> dict:
        self.pick_models()
        body = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 900, "responseMimeType": "application/json"},
        }
        r = httpx.post(f"{BASE}/{self.gen_model}:generateContent", headers=self._headers(), json=body, timeout=60)
        r.raise_for_status()
        cand = r.json().get("candidates", [{}])[0]
        text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            return json.loads(text[start:end + 1]) if start >= 0 else {"answer": text, "used": [], "found": bool(text)}
