"""OpenAI-клиент для семантических фаз (решение владельца 2026-08-10: не Gemini).

Паттерн — tools/scout/enrich.py: chat/completions + strict json_schema +
reasoning_effort low; ключ OPENAI_API_KEY из env или tools/scout/.env.
Кэш на диске (remlab_knowledge_db_v1/llm_cache, gitignored) — локальная
оптимизация; КАНОН вердиктов — дистиллированные реестры/артефакты в git.
Правила: счётчик отказов обязателен, молчаливый except запрещён
(fail поднимается после ретраев; батч-цикл считает и报 отчитывается).
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .canonical import jcs_sha256

API = "https://api.openai.com/v1/chat/completions"
MODEL_CHEAP = "gpt-5.6-luna"
MODEL_STRONG = "gpt-5.6-terra"
# $/1M токенов (tools/scout/golden_eval.py)
PRICE = {MODEL_CHEAP: (0.20, 1.20), MODEL_STRONG: (2.00, 12.00)}

REPO_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = REPO_ROOT / "remlab_knowledge_db_v1" / "llm_cache"


class LLMDisabled(RuntimeError):
    pass


def api_key() -> str:
    k = os.environ.get("OPENAI_API_KEY")
    if k:
        return k
    envf = REPO_ROOT / "tools" / "scout" / ".env"
    if envf.exists():
        for line in envf.read_text().splitlines():
            if line.startswith("OPENAI_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise SystemExit("нет OPENAI_API_KEY (env или tools/scout/.env)")


@dataclass
class LLMStats:
    calls: int = 0
    cache_hits: int = 0
    failures: int = 0
    retries: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd_by_model: dict = field(default_factory=dict)

    def add_usage(self, model: str, usage: dict) -> None:
        pt = usage.get("prompt_tokens", 0)
        ct = usage.get("completion_tokens", 0)
        self.prompt_tokens += pt
        self.completion_tokens += ct
        pin, pout = PRICE.get(model, (0, 0))
        cost = pt / 1e6 * pin + ct / 1e6 * pout
        self.cost_usd_by_model[model] = round(
            self.cost_usd_by_model.get(model, 0.0) + cost, 6)

    @property
    def cost_usd(self) -> float:
        return round(sum(self.cost_usd_by_model.values()), 4)

    def as_dict(self) -> dict:
        return {"calls": self.calls, "cache_hits": self.cache_hits,
                "failures": self.failures, "retries": self.retries,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "cost_usd": self.cost_usd,
                "cost_usd_by_model": self.cost_usd_by_model}


def call_json(model: str, system: str, user: str, schema_name: str,
              schema: dict, stats: LLMStats, max_retries: int = 3) -> dict:
    """Structured-output вызов с дисковым кэшем. Возвращает распарсенный объект."""
    cache_key = jcs_sha256({"model": model, "system": system, "user": user,
                            "schema": schema})
    cache_path = CACHE_DIR / f"{cache_key}.json"
    if cache_path.exists():
        stats.cache_hits += 1
        return json.loads(cache_path.read_text(encoding="utf-8"))["response"]
    if os.environ.get("KDB_NO_LLM"):
        raise LLMDisabled("KDB_NO_LLM=1 и нет кэша")

    body = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": schema_name,
                                            "strict": True,
                                            "schema": schema}},
        "reasoning_effort": "low",
    }
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                API, data=json.dumps(body).encode(),
                headers={"Authorization": f"Bearer {api_key()}",
                         "Content-Type": "application/json"})
            r = json.load(urllib.request.urlopen(req, timeout=180))
            stats.calls += 1
            stats.add_usage(model, r.get("usage", {}))
            content = r["choices"][0]["message"]["content"]
            obj = json.loads(content)
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(
                {"model": model, "response": obj,
                 "usage": r.get("usage", {})}, ensure_ascii=False),
                encoding="utf-8")
            return obj
        except (urllib.error.URLError, json.JSONDecodeError, KeyError,
                TimeoutError) as e:
            last_err = e
            stats.retries += 1
            time.sleep(2 * (attempt + 1))
    stats.failures += 1
    raise RuntimeError(f"LLM-вызов не удался после {max_retries} попыток: "
                       f"{last_err}")
