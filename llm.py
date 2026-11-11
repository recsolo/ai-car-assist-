"""Talk to the local Ollama model, and build answers without it when it is offline."""
import json
import os
import re
from typing import Optional

import httpx

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
MODEL_NAME = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
# The first request loads the model into memory, which is slow on a laptop.
TIMEOUT = httpx.Timeout(180.0, connect=3.0)

SYSTEM_PROMPT = (
    "You are a cautious, friendly car diagnostic assistant for beginners. "
    "Use ONLY the verified facts you are given. Never invent causes, prices, part numbers, "
    "or repair steps that are not in the facts. If the facts do not cover a question, say you "
    "do not have verified information on that and suggest asking a mechanic. "
    "Use short sentences and plain English. Explain any technical word you use."
)

EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "advice": {"type": "string"},
        "voice_response": {"type": "string"},
    },
    "required": ["summary", "advice", "voice_response"],
}


class LLMUnavailable(Exception):
    """Ollama is not running, the model is missing, or it returned something unusable."""


def describe_vehicle(vehicle: dict) -> str:
    name = " ".join(str(vehicle[k]) for k in ("year", "make", "model") if vehicle.get(k))
    name = name or "unknown vehicle"
    if vehicle.get("mileage") is not None:
        name += f" with {vehicle['mileage']:,} miles"
    return name


def cost_range(fact: dict) -> str:
    low, high = fact["repair_min"], fact["repair_max"]
    if low == 0:
        return f"free to ${high:,}"
    return f"${low:,} to ${high:,}"


def facts_block(vehicle: dict, fact: dict, mileage_note: Optional[str],
                past_codes: list[str]) -> str:
    lines = [
        f"Vehicle: {describe_vehicle(vehicle)}",
        f"Code: {fact['code']}",
        "",
        "Verified facts:",
        f"- title: {fact['title']}",
        f"- what it means: {fact['plain_english']}",
        f"- severity: {fact['severity']}",
        f"- safe to drive: {fact['safe_to_drive']}",
        f"- common causes: {'; '.join(fact['common_causes'])}",
        f"- what to check next: {'; '.join(fact['next_checks'])}",
        f"- typical repair cost: {cost_range(fact)}",
        f"- misdiagnosis warning: {fact['misdiagnosis_notes']}",
    ]
    if mileage_note:
        lines.append(f"- note for this mileage: {mileage_note}")
    if past_codes:
        lines.append(f"- codes seen earlier on this same vehicle: {', '.join(past_codes)}")
    return "\n".join(lines)


def _chat(messages: list[dict], fmt=None) -> str:
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "stream": False,
        "keep_alive": "30m",
        "options": {"temperature": 0.2},
    }
    if fmt is not None:
        payload["format"] = fmt
    try:
        resp = httpx.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=TIMEOUT)
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:200]
        raise LLMUnavailable(f"Ollama returned an error: {detail}") from exc
    except httpx.HTTPError as exc:
        raise LLMUnavailable(f"Could not reach Ollama at {OLLAMA_URL}") from exc
    except (KeyError, ValueError, TypeError) as exc:
        raise LLMUnavailable("Ollama returned an unexpected response") from exc
    if not isinstance(content, str) or not content.strip():
        raise LLMUnavailable("The model returned an empty answer")
    return content.strip()


def _extract_json(text: str) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise LLMUnavailable("The model did not return JSON") from None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            raise LLMUnavailable("The model returned malformed JSON") from None
    if not isinstance(data, dict):
        raise LLMUnavailable("The model returned JSON in the wrong shape")
    return data


def _as_text(value) -> str:
    """Small models sometimes return a list or number where a string was asked for."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return " ".join(_as_text(v) for v in value).strip()
    return "" if value is None else str(value)


def explain(vehicle: dict, fact: dict, mileage_note: Optional[str],
            past_codes: list[str]) -> dict:
    """Ask the model for a summary, advice and a spoken answer grounded in the facts."""
    user = (
        f"{facts_block(vehicle, fact, mileage_note, past_codes)}\n\n"
        "Explain this code to the driver. Return JSON with exactly these keys:\n"
        "- summary: 2 sentences on what is going on, for this specific vehicle.\n"
        "- advice: 2 to 3 sentences on what the driver should do next, cheapest checks first.\n"
        "- voice_response: 2 to 3 short sentences to be read aloud, like a knowledgeable "
        "friend talking. No lists, no symbols, and say the code one character at a time."
    )
    raw = _chat(
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
        fmt=EXPLAIN_SCHEMA,
    )
    data = _extract_json(raw)
    answer = {key: _as_text(data.get(key)) for key in ("summary", "advice", "voice_response")}
    if not answer["summary"]:
        raise LLMUnavailable("The model left the summary empty")
    answer["voice_response"] = answer["voice_response"] or answer["summary"]
    return answer


def followup(vehicle: dict, fact: dict, mileage_note: Optional[str], past_codes: list[str],
             history: list[dict], question: str) -> str:
    """Answer a follow-up question about the same vehicle and code."""
    system = (
        f"{SYSTEM_PROMPT}\n\n{facts_block(vehicle, fact, mileage_note, past_codes)}\n\n"
        "Answer the driver's follow-up question in 2 to 4 short spoken-style sentences. "
        "No lists or symbols."
    )
    messages = [{"role": "system", "content": system}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": question})
    return _chat(messages)


def status() -> dict:
    """Whether Ollama is reachable and has the configured model."""
    info = {"model": MODEL_NAME, "running": False, "model_ready": False}
    try:
        resp = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=1.5)
        resp.raise_for_status()
        names = [m.get("name", "") for m in resp.json().get("models", [])]
    except (httpx.HTTPError, ValueError, AttributeError):
        return info
    info["running"] = True
    wanted = MODEL_NAME if ":" in MODEL_NAME else f"{MODEL_NAME}:latest"
    info["model_ready"] = wanted in names
    return info


# --- Answers built straight from the database, used when the model is unavailable ---

def spell_code(code: str) -> str:
    """'P0420' -> 'P 0 4 2 0' so text-to-speech reads it one character at a time."""
    return " ".join(code)


def offline_explain(fact: dict, mileage_note: Optional[str]) -> dict:
    checks = fact["next_checks"]
    advice = f"Start here: {checks[0]}. {fact['misdiagnosis_notes']}"
    if mileage_note:
        advice += f" {mileage_note}"
    return {
        "summary": fact["plain_english"],
        "advice": advice,
        "voice_response": (
            f"Code {spell_code(fact['code'])}. {fact['plain_english']} "
            f"Is it safe to drive? {fact['safe_to_drive']} "
            + (f"A typical repair costs up to {fact['repair_max']:,} dollars, and the fix "
               "is sometimes free." if fact["repair_min"] == 0 else
               f"A typical repair runs {fact['repair_min']:,} to {fact['repair_max']:,} dollars.")
        ),
    }


_OFFLINE_TOPICS = (
    (("safe", "drive", "driving", "danger", "tow", "trip", "work"),
     lambda f: f"Is it safe to drive? {f['safe_to_drive']}"),
    (("cost", "price", "expensive", "much", "pay", "cheap", "money"),
     lambda f: f"A typical repair runs {cost_range(f)}. {f['misdiagnosis_notes']}"),
    (("cause", "why", "wrong", "reason", "broke", "happen"),
     lambda f: f"The common causes are: {', '.join(f['common_causes'])}."),
    (("check", "fix", "do", "next", "repair", "start", "myself", "diy"),
     lambda f: f"Check these first: {', '.join(f['next_checks'])}. {f['misdiagnosis_notes']}"),
    (("serious", "urgent", "bad", "severe", "wait", "ignore"),
     lambda f: f"The severity is {f['severity']}. {f['safe_to_drive']}"),
)


def offline_followup(fact: dict, question: str) -> str:
    """Best matching verified fact for the question, without a language model."""
    words = set(re.findall(r"[a-z]+", question.lower()))
    for keywords, answer in _OFFLINE_TOPICS:
        if words & set(keywords):
            return answer(fact)
    return (
        "The AI model is offline, so I can only read back the verified facts. "
        f"{fact['plain_english']} {fact['safe_to_drive']}"
    )
