"""Minimal Gemini REST client (the free tier is enough for the demo).

Model names change often, so by default we ask the API which models this key
can use, rank the plain Flash models by version, and keep a short fallback list:
if the best model is rate limited or unavailable, the next one answers.
Override with GEMINI_MODEL (comma-separated list allowed) and GEMINI_EMBED_MODEL.
"""
from __future__ import annotations

import json
import os
import re

import httpx

BASE = "https://generativelanguage.googleapis.com/v1beta"
SKIP = ("image", "tts", "audio", "live", "omni", "banana", "lyria", "research", "customtools", "exp", "gemma", "robotics", "computer")


def _version(name: str) -> tuple:
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    return (float(m.group(1)) if m else 0.0, "preview" not in name, "latest" not in name)


class GeminiError(Exception):
    pass


class Gemini:
    def __init__(self, key: str | None = None):
        self.key = key or os.getenv("GEMINI_API_KEY", "").strip()
        self._models: list[dict] | None = None
        pinned = [m.strip() for m in os.getenv("GEMINI_MODEL", "").split(",") if m.strip()]
        self.gen_models: list[str] = [m if m.startswith("models/") else f"models/{m}" for m in pinned]
        e = os.getenv("GEMINI_EMBED_MODEL", "").strip()
        self.embed_model = (e if e.startswith("models/") else f"models/{e}") if e else None

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    @property
    def gen_model(self) -> str | None:
        return self.gen_models[0] if self.gen_models else None

    def _headers(self):
        return {"x-goog-api-key": self.key, "Content-Type": "application/json"}

    def models(self) -> list[dict]:
        if self._models is None:
            r = httpx.get(f"{BASE}/models", headers=self._headers(), params={"pageSize": 1000}, timeout=30)
            r.raise_for_status()
            self._models = r.json().get("models", [])
        return self._models

    def pick_models(self):
        if self.gen_models and self.embed_model:
            return
        names = [(m["name"], m.get("supportedGenerationMethods", [])) for m in self.models()]
        if not self.gen_models:
            gen = [n for n, s in names if "generateContent" in s and "flash" in n and not any(x in n for x in SKIP)]
            full = sorted([n for n in gen if "lite" not in n], key=_version, reverse=True)
            lite = sorted([n for n in gen if "lite" in n], key=_version, reverse=True)
            # Token saving: the newest Flash-Lite answers; a full Flash model only steps in
            # when Lite is rate limited or fails. GEMINI_MODEL overrides this order.
            self.gen_models = (lite[:1] + full[:1] + lite[1:2]) or ["models/gemini-flash-lite-latest"]
        if not self.embed_model:
            emb = [n for n, s in names if "embedContent" in s and "gemini-embedding" in n]
            self.embed_model = sorted(emb, key=_version, reverse=True)[0] if emb else "models/gemini-embedding-001"
            stable = [n for n in emb if "preview" not in n and "exp" not in n]
            if stable:
                self.embed_model = sorted(stable, key=lambda n: (n.endswith("001"), n))[0]

    # ---------- embeddings ----------
    def embed(self, texts: list[str], task: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
        self.pick_models()
        out: list[list[float]] = []
        for i in range(0, len(texts), 50):
            batch = texts[i:i + 50]
            body = {"requests": [{"model": self.embed_model, "content": {"parts": [{"text": t[:6000]}]}, "taskType": task}
                                 for t in batch]}
            r = httpx.post(f"{BASE}/{self.embed_model}:batchEmbedContents", headers=self._headers(), json=body, timeout=120)
            if r.status_code >= 400:
                raise GeminiError(f"embed {r.status_code}: {r.text[:200]}")
            out.extend(e["values"] for e in r.json()["embeddings"])
        return out

    # ---------- generation ----------
    def _call(self, model: str, body: dict) -> dict:
        r = httpx.post(f"{BASE}/{model}:generateContent", headers=self._headers(), json=body, timeout=60)
        if r.status_code == 400 and "thinking" in r.text.lower() and "thinkingConfig" in body.get("generationConfig", {}):
            body = json.loads(json.dumps(body))
            body["generationConfig"].pop("thinkingConfig")
            r = httpx.post(f"{BASE}/{model}:generateContent", headers=self._headers(), json=body, timeout=60)
        if r.status_code >= 400:
            raise GeminiError(f"{model} {r.status_code}: {r.text[:300]}")
        data = r.json()
        cand = (data.get("candidates") or [{}])[0]
        text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []) if not p.get("thought"))
        if not text.strip():
            raise GeminiError(f"{model} returned no text ({cand.get('finishReason')})")
        return {"text": text, "model": model}

    def generate(self, system: str, prompt: str, schema: dict | None = None, temperature: float = 0.2,
                 max_tokens: int = 1024) -> dict:
        """Returns {"text": ..., "model": ...}, trying each model in turn on rate limits or errors."""
        self.pick_models()
        errors = []
        for model in self.gen_models:
            cfg = {"temperature": temperature, "maxOutputTokens": max_tokens}
            # Short answers from given sources: keep model "thinking" minimal for speed and quota.
            cfg["thinkingConfig"] = {"thinkingLevel": "minimal"} if "gemini-3" in model else {"thinkingBudget": 0}
            if schema:
                cfg["responseMimeType"] = "application/json"
                cfg["responseSchema"] = schema
            body = {"system_instruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": cfg}
            try:
                return self._call(model, body)
            except (GeminiError, httpx.HTTPError) as e:
                errors.append(str(e))
                continue
        raise GeminiError(" | ".join(errors))

    def generate_json(self, system: str, prompt: str, schema: dict | None = None) -> dict:
        out = self.generate(system, prompt, schema=schema or {"type": "OBJECT"})
        text = out["text"]
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            data = json.loads(text[start:end + 1]) if start >= 0 else {"answer": text, "used": [], "found": bool(text)}
        data["_model"] = out["model"]
        return data
