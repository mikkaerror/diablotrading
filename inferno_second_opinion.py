from __future__ import annotations

"""Second-model devil's advocate (ChatGPT) for desk candidates.

A different model reviews each pending paper candidate and writes the single
strongest case AGAINST it, using only the facts we hand it. Two models that
disagree catch blind spots one model shares with itself.

Advisory only: the output is quoted in the Desk Editor email and never feeds
the approval policy (inferno_paper_delegate.py stays deterministic). Runs on
the Mac (the Cowork VM cannot reach api.openai.com). Needs OPENAI_API_KEY in
.env.inferno; without it, or without network, it records a status and exits 0.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

try:  # loads .env.inferno into os.environ on the Mac
    import inferno_config  # noqa: F401
except Exception:  # pragma: no cover - config is optional here
    pass

from inferno_desk_editor import DATA_DIR, decisions_section

SECOND_OPINION_STAGE = "second-opinion-research-only"
SECOND_OPINION_FILE = DATA_DIR / "inferno_second_opinion.json"
API_URL = os.environ.get("OPENAI_API_URL", "https://api.openai.com/v1/chat/completions")
MODELS_URL = os.environ.get("OPENAI_MODELS_URL", "https://api.openai.com/v1/models")
# No hard-coded model: names change. Unless INFERNO_SECOND_OPINION_MODEL is set,
# pick the cheapest-tier text model the account actually has.
MODEL_PREFERENCE = ("luna", "nano", "mini")
MODEL_EXCLUDE = ("transcribe", "tts", "audio", "realtime", "image", "embedding", "search", "moderation", "whisper", "dall")
MAX_WORDS = 35
TIMEOUT_SECONDS = 30

SYSTEM_PROMPT = (
    "You are a skeptical options risk reviewer on a small paper-trading desk. "
    "Given one candidate trade as JSON facts, reply with ONE sentence (max "
    f"{MAX_WORDS} words) stating the strongest case AGAINST taking it. Use only "
    "numbers that appear in the facts. No advice to buy or sell, no preamble."
)


def candidate_facts(decision: dict[str, Any]) -> dict[str, Any]:
    keys = ("ticker", "strategy", "expiration", "maxLoss", "breakevens", "daysUntilEarnings",
            "readiness", "riskBlocks", "tickerShadow", "strategyShadow")
    return {key: decision.get(key) for key in keys}


def pick_model(model_ids: list[str]) -> str | None:
    """Cheapest-tier chat model by name hint; newest-looking id wins ties."""
    usable = [m for m in model_ids if not any(word in m.lower() for word in MODEL_EXCLUDE)]
    for hint in MODEL_PREFERENCE:
        matches = sorted((m for m in usable if hint in m.lower()), reverse=True)
        if matches:
            return matches[0]
    return None


def list_models(api_key: str, opener=urllib.request.urlopen) -> list[str]:
    request = urllib.request.Request(MODELS_URL, headers={"Authorization": f"Bearer {api_key}"})
    with opener(request, timeout=TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return [row.get("id", "") for row in payload.get("data") or [] if row.get("id")]


def ask_model(facts: dict[str, Any], api_key: str, model: str, opener=urllib.request.urlopen) -> str:
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(facts)},
        ],
    }).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with opener(request, timeout=TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))
    text = payload["choices"][0]["message"]["content"].strip().replace("\n", " ")
    words = text.split()
    return " ".join(words[: MAX_WORDS + 5])


def build_second_opinion(
    data_dir: Path = DATA_DIR,
    env: dict[str, str] | None = None,
    asker=ask_model,
    now: datetime | None = None,
    model_lister=list_models,
) -> dict[str, Any]:
    env = env if env is not None else dict(os.environ)
    now = now or datetime.now().astimezone()
    payload: dict[str, Any] = {
        "generatedAt": now.isoformat(),
        "stage": SECOND_OPINION_STAGE,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "advisoryOnly": True,
        "model": env.get("INFERNO_SECOND_OPINION_MODEL", "").strip() or None,
        "status": "ok",
        "items": [],
        "citations": ["coordination/prompts/desk_editor_agent.md", "inferno_desk_editor.decisions_section"],
    }
    decisions = decisions_section(data_dir)
    if not decisions:
        payload["status"] = "no-candidates"
        return payload
    api_key = env.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        payload["status"] = "no-key"
        return payload
    if not payload["model"]:
        try:
            payload["model"] = pick_model(model_lister(api_key))
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError, OSError) as exc:
            payload["status"] = "unavailable"
            payload["errors"] = [f"model list: {type(exc).__name__}"]
            return payload
        if not payload["model"]:
            payload["status"] = "no-model"
            return payload
    for decision in decisions:
        try:
            challenge = asker(candidate_facts(decision), api_key, payload["model"])
            payload["items"].append({"ticker": decision["ticker"], "challenge": challenge})
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError, OSError) as exc:
            payload["status"] = "partial" if payload["items"] else "unavailable"
            payload.setdefault("errors", []).append(f"{decision['ticker']}: {type(exc).__name__}")
    return payload


def save_second_opinion(payload: dict[str, Any]) -> None:
    from inferno_io import atomic_write_json

    atomic_write_json(SECOND_OPINION_FILE, payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ChatGPT devil's advocate for pending candidates (advisory).")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    args = parser.parse_args(argv)
    if args.command == "status":
        try:
            print(SECOND_OPINION_FILE.read_text(encoding="utf-8"))
            return 0
        except OSError:
            print("No second opinion yet.")
            return 1
    payload = build_second_opinion()
    save_second_opinion(payload)
    print(f"Second opinion: {payload['status']} | model {payload['model']} | {len(payload['items'])} item(s)")
    for item in payload["items"]:
        print(f"- {item['ticker']}: {item['challenge']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
