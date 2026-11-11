"""AI Car Voice Assistant: the web app.

Start it with:  python app.py
Then open:      http://127.0.0.1:8000
"""
import ipaddress
import os
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator

import db
import llm
import parsing
import voice_handler

BASE_DIR = Path(__file__).resolve().parent
SEVERITY_RANK = {name: rank for rank, name in enumerate(db.SEVERITIES)}
# Extra names this app may be reached by, e.g. ALLOWED_HOSTS=garage-pc,garage-pc.local
EXTRA_HOSTS = {h.strip().lower() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()}


@asynccontextmanager
async def lifespan(app: FastAPI):
    count = db.init_db()
    print(f"Loaded {count} verified codes into {db.DB_PATH}")
    yield


app = FastAPI(title="AI Car Voice Assistant", lifespan=lifespan)


def _host_allowed(host_header: Optional[str]) -> bool:
    """Only answer when addressed as localhost, by IP address, or by an allowed name.

    A hostile website can point its own domain name at 127.0.0.1 to reach local
    apps ("DNS rebinding"). It cannot do that with a bare IP address.
    """
    try:
        name = (urlparse(f"//{host_header or ''}").hostname or "").lower()
    except ValueError:
        return False
    if name == "localhost" or name in EXTRA_HOSTS:
        return True
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False


@app.middleware("http")
async def local_requests_only(request: Request, call_next):
    """Refuse requests that come from other websites.

    Without this, any web page open in your browser could ask this app to
    switch on the microphone or speak through your speakers.
    """
    host = request.headers.get("host")
    if not _host_allowed(host):
        return JSONResponse(
            {"detail": "This address is not allowed. Use the computer's IP address, "
                       "or add the name to ALLOWED_HOSTS."}, status_code=403)
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != host:
        return JSONResponse({"detail": "Cross-site requests are not allowed."}, status_code=403)
    return await call_next(request)


class Vehicle(BaseModel):
    year: Optional[int] = Field(None, ge=1980, le=2100)
    make: Optional[str] = Field(None, max_length=40)
    model: Optional[str] = Field(None, max_length=40)
    mileage: Optional[int] = Field(None, ge=0, le=2_000_000)

    @field_validator("make", "model")
    @classmethod
    def blank_to_none(cls, value):
        value = (value or "").strip()
        return value or None


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)


class ExplainRequest(BaseModel):
    vehicle: Vehicle = Vehicle()
    code: str = Field(max_length=200)
    record: bool = True


class FollowupRequest(BaseModel):
    vehicle: Vehicle = Vehicle()
    code: str = Field(max_length=20)
    related: list[str] = Field(default_factory=list, max_length=5)
    question: str = Field(min_length=1, max_length=500)
    history: list[Turn] = Field(default_factory=list, max_length=12)


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1500)


class ListenRequest(BaseModel):
    max_seconds: float = Field(12.0, ge=2, le=30)


def _resolve_codes(text: str) -> tuple[str, list[str]]:
    """Find every code in 'P0420', 'p 0420' or a whole sentence.

    Returns the main code and the others. The main code is the most serious one
    the database knows, because that is the one to deal with first.
    """
    codes = parsing.find_codes(text)
    if not codes:
        raise HTTPException(
            422, "That does not look like a trouble code. Codes look like P0420: "
                 "one letter (P, B, C or U) followed by four digits.")
    known = {code: db.get_fact(code) for code in codes}
    ranked = sorted((c for c in codes if known[c]),
                    key=lambda c: -SEVERITY_RANK[known[c]["severity"]])
    main = ranked[0] if ranked else codes[0]
    return main, [c for c in codes if c != main]


def _related_facts(codes: list[str]) -> list[dict]:
    facts = (db.get_fact(code) for code in codes if parsing.is_code(code))
    return [db.brief(fact) for fact in facts if fact]


def _explain(req: ExplainRequest, use_ai: bool) -> dict:
    code, others = _resolve_codes(req.code)
    vehicle = req.vehicle.model_dump()
    fact = db.get_fact(code)
    if fact is None:
        return {
            "known": False,
            "code": code,
            "message": (
                f"I do not have verified facts for {code} yet, so I will not guess. "
                f"{parsing.describe_code_structure(code)} "
                "You can add it to data/dtc_codes.json and restart the app."
            ),
        }

    related = _related_facts(others)
    note = db.mileage_note(fact, vehicle["mileage"])
    past = [c for c in db.previous_codes(vehicle, code) if c not in others]
    answer, source, notice = llm.offline_explain(fact, note, related), "database", None
    if use_ai:
        try:
            answer, source = llm.explain(vehicle, fact, note, past, related), "ai"
        except llm.LLMUnavailable as exc:
            notice = str(exc)
    if req.record:
        db.record_lookup(vehicle, code)

    return {
        "known": True,
        "code": code,
        "vehicle": vehicle,
        "fact": fact,
        "cost_range": llm.cost_range(fact),
        "mileage_note": note,
        "previous_codes": past,
        "related": related,
        "unknown_codes": [c for c in others if c not in {r["code"] for r in related}],
        "answer": answer,
        "source": source,
        "notice": notice,
    }


@app.get("/")
def home():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/status")
def status():
    return {
        "llm": llm.status(),
        "voice": {"stt": voice_handler.stt_status(), "tts": voice_handler.tts_available()},
        "codes": len(db.list_codes()),
    }


@app.get("/api/codes")
def codes():
    return db.list_codes()


@app.get("/api/history")
def history():
    return db.recent_lookups()


@app.post("/api/lookup")
def lookup(req: ExplainRequest):
    """The verified facts for a code, straight from the database. Returns at once."""
    return _explain(req, use_ai=False)


@app.post("/api/explain")
def explain(req: ExplainRequest):
    """The verified facts plus the AI model's explanation. Can take a while."""
    return _explain(req, use_ai=True)


@app.post("/api/followup")
def followup(req: FollowupRequest):
    code, _ = _resolve_codes(req.code)
    fact = db.get_fact(code)
    if fact is None:
        raise HTTPException(404, f"No verified facts for {code}.")
    vehicle = req.vehicle.model_dump()
    related = _related_facts(req.related)
    note = db.mileage_note(fact, vehicle["mileage"])
    past = db.previous_codes(vehicle, code)
    try:
        answer = llm.followup(vehicle, fact, note, past,
                              [t.model_dump() for t in req.history], req.question, related)
        source = "ai"
    except llm.LLMUnavailable:
        answer = llm.offline_followup(fact, req.question)
        source = "database"
    return {"answer": answer, "source": source}


@app.post("/api/listen")
def listen(req: ListenRequest = ListenRequest()):
    """Record one spoken question from this computer's microphone."""
    try:
        text = voice_handler.listen(req.max_seconds)
    except voice_handler.VoiceError as exc:
        raise HTTPException(503, str(exc)) from exc
    parsed = parsing.parse_question(text, db.known_codes())
    parsed["codes"] = parsing.find_codes(text)
    return {"text": text, "parsed": parsed}


@app.post("/api/speak")
def speak(req: SpeakRequest):
    """Read text aloud through this computer's speakers."""
    try:
        voice_handler.speak(req.text)
    except voice_handler.VoiceError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    url = f"http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}"
    print(f"Open {url} in your browser")

    # Load both models in the background so the first question is not slow.
    threading.Thread(target=llm.warm_up, daemon=True).start()
    threading.Thread(target=voice_handler.warm_up, daemon=True).start()
    if os.environ.get("NO_BROWSER") != "1":
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()

    uvicorn.run(app, host=host, port=port)
