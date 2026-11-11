"""AI Car Voice Assistant: the web app.

Start it with:  python app.py
Then open:      http://127.0.0.1:8000
"""
import os
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    count = db.init_db()
    print(f"Loaded {count} verified codes into {db.DB_PATH}")
    yield


app = FastAPI(title="AI Car Voice Assistant", lifespan=lifespan)


@app.middleware("http")
async def same_origin_only(request: Request, call_next):
    """Refuse requests sent by other websites.

    Without this, any web page open in your browser could ask this app to
    switch on the microphone or speak through your speakers.
    """
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.headers.get("host"):
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


class FollowupRequest(BaseModel):
    vehicle: Vehicle = Vehicle()
    code: str = Field(max_length=20)
    question: str = Field(min_length=1, max_length=500)
    history: list[Turn] = Field(default_factory=list, max_length=12)


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1500)


class ListenRequest(BaseModel):
    max_seconds: float = Field(12.0, ge=2, le=30)


def _resolve_code(text: str) -> str:
    """Accept 'P0420', 'p 0420', or a whole sentence containing a code."""
    code = parsing.pick_code(text, db.known_codes())
    if not code:
        raise HTTPException(
            422, "That does not look like a trouble code. Codes look like P0420: "
                 "one letter (P, B, C or U) followed by four digits.")
    return code


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


@app.post("/api/explain")
def explain(req: ExplainRequest):
    code = _resolve_code(req.code)
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

    note = db.mileage_note(fact, vehicle["mileage"])
    past = db.previous_codes(vehicle, code)
    try:
        answer = llm.explain(vehicle, fact, note, past)
        source, notice = "ai", None
    except llm.LLMUnavailable as exc:
        answer = llm.offline_explain(fact, note)
        source, notice = "database", str(exc)
    db.record_lookup(vehicle, code)

    return {
        "known": True,
        "code": code,
        "vehicle": vehicle,
        "fact": fact,
        "cost_range": llm.cost_range(fact),
        "mileage_note": note,
        "previous_codes": past,
        "answer": answer,
        "source": source,
        "notice": notice,
    }


@app.post("/api/followup")
def followup(req: FollowupRequest):
    code = _resolve_code(req.code)
    fact = db.get_fact(code)
    if fact is None:
        raise HTTPException(404, f"No verified facts for {code}.")
    vehicle = req.vehicle.model_dump()
    note = db.mileage_note(fact, vehicle["mileage"])
    past = db.previous_codes(vehicle, code)
    try:
        answer = llm.followup(vehicle, fact, note, past,
                              [t.model_dump() for t in req.history], req.question)
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
    return {"text": text, "parsed": parsing.parse_question(text, db.known_codes())}


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
    print(f"Open http://{host}:{port} in your browser")
    uvicorn.run(app, host=host, port=port)
