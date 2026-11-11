"""Voice in and voice out, all local.

Nothing here is imported until it is first used, so the app still starts and
works with typed input when the microphone or speech packages are missing.
"""
import importlib.util
import os
import queue
import threading
from typing import Optional

import numpy as np

SAMPLE_RATE = 16000
CHUNK_SECONDS = 0.1
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base.en")
# Nudges the speech model toward writing codes as "P0420" instead of "P zero four twenty".
WHISPER_HINT = (
    "Car diagnostic trouble codes such as P0420, P0300, P0171 and U0100. "
    "A 2015 Honda Accord with 128,000 miles."
)


class VoiceError(Exception):
    """A voice problem with a message that is safe to show the user."""


class Endpointer:
    """Decides when the speaker has finished, from the loudness of each audio chunk.

    Feed it the RMS level of each chunk. `done` turns True once speech has been
    heard and then followed by a pause, or when nobody speaks at all.
    """

    def __init__(self, chunk_seconds: float = CHUNK_SECONDS, silence_seconds: float = 1.2,
                 no_speech_seconds: float = 6.0, min_threshold: float = 0.012):
        self._chunk = chunk_seconds
        self._silence_limit = silence_seconds
        self._no_speech_limit = no_speech_seconds
        self._min_threshold = min_threshold
        self._calibration: list[float] = []
        self._threshold: Optional[float] = None
        self._loud_run = 0
        self._silence = 0.0
        self._elapsed = 0.0
        self.heard_speech = False
        self.done = False

    def feed(self, rms: float) -> bool:
        self._elapsed += self._chunk
        if self._threshold is None:
            # The first 0.3 s measures background noise so a noisy garage still works.
            self._calibration.append(rms)
            if len(self._calibration) * self._chunk >= 0.3:
                noise = float(np.median(self._calibration))
                self._threshold = max(self._min_threshold, noise * 3.0)
            return self.done

        if rms >= self._threshold:
            self._loud_run += 1
            self._silence = 0.0
            if self._loud_run >= 2:
                self.heard_speech = True
        else:
            self._loud_run = 0
            self._silence += self._chunk

        if self.heard_speech and self._silence >= self._silence_limit:
            self.done = True
        elif not self.heard_speech and self._elapsed >= self._no_speech_limit:
            self.done = True
        return self.done


_record_lock = threading.Lock()
_whisper = None
_whisper_lock = threading.Lock()


def record(max_seconds: float = 12.0) -> np.ndarray:
    """Record from the default microphone until the speaker pauses."""
    try:
        import sounddevice as sd
    except (ImportError, OSError) as exc:
        raise VoiceError(f"Microphone support is not available ({exc}).") from exc

    if not _record_lock.acquire(blocking=False):
        raise VoiceError("Already listening. Wait for the current recording to finish.")
    try:
        chunks: "queue.Queue[np.ndarray]" = queue.Queue()

        def on_audio(indata, frames, time_info, status):
            chunks.put(indata[:, 0].copy())

        endpointer = Endpointer()
        recorded: list[np.ndarray] = []
        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                blocksize=int(SAMPLE_RATE * CHUNK_SECONDS),
                                callback=on_audio):
                for _ in range(int(max_seconds / CHUNK_SECONDS)):
                    chunk = chunks.get(timeout=2.0)
                    recorded.append(chunk)
                    if endpointer.feed(float(np.sqrt(np.mean(chunk ** 2)))):
                        break
        except queue.Empty as exc:
            raise VoiceError("The microphone stopped sending audio.") from exc
        except Exception as exc:  # sounddevice raises PortAudioError for device problems
            raise VoiceError(
                f"Could not open the microphone ({exc}). Check that one is plugged in "
                "and that this app is allowed to use it."
            ) from exc
    finally:
        _record_lock.release()

    if not endpointer.heard_speech:
        raise VoiceError("I did not hear anything. Check your microphone and try again.")
    return np.concatenate(recorded)


def _load_whisper():
    global _whisper
    with _whisper_lock:
        if _whisper is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise VoiceError(f"Speech-to-text is not installed ({exc}).") from exc
            try:
                # int8 on CPU is fast enough for short questions on a laptop.
                _whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
            except Exception as exc:
                raise VoiceError(
                    f"Could not load the '{WHISPER_MODEL}' speech model ({exc}). The first "
                    "run needs an internet connection to download it."
                ) from exc
        return _whisper


def transcribe(audio: np.ndarray) -> str:
    """Turn 16 kHz mono float audio into text."""
    model = _load_whisper()
    segments, _ = model.transcribe(
        audio.astype(np.float32), language="en", beam_size=5, initial_prompt=WHISPER_HINT
    )
    return " ".join(segment.text.strip() for segment in segments).strip()


def listen(max_seconds: float = 12.0) -> str:
    """Record one spoken question and return it as text."""
    text = transcribe(record(max_seconds))
    if not text:
        raise VoiceError("I could not make out any words. Try again a little closer to the mic.")
    return text


# --- Text to speech -------------------------------------------------------------
# pyttsx3 must be driven from one thread, one utterance at a time. Starting a new
# engine in a new thread per answer (as the original guide did) crashes or hangs
# when two answers overlap, so everything goes through a single worker.

_speech_queue: "queue.Queue[str]" = queue.Queue()
_speech_worker: Optional[threading.Thread] = None
_speech_worker_lock = threading.Lock()


def _speech_loop() -> None:
    import pyttsx3

    while True:
        text = _speech_queue.get()
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", 165)
            engine.say(text)
            engine.runAndWait()
            engine.stop()
        except Exception as exc:
            print(f"Text-to-speech failed: {exc}")


def speak(text: str) -> None:
    """Queue text to be read aloud through the computer's speakers."""
    global _speech_worker
    if not tts_available():
        raise VoiceError("Text-to-speech (pyttsx3) is not installed.")
    with _speech_worker_lock:
        if _speech_worker is None:
            _speech_worker = threading.Thread(target=_speech_loop, daemon=True)
            _speech_worker.start()
    # Drop anything still waiting so a new answer is not stuck behind old ones.
    while True:
        try:
            _speech_queue.get_nowait()
        except queue.Empty:
            break
    _speech_queue.put(text)


def tts_available() -> bool:
    return importlib.util.find_spec("pyttsx3") is not None


def stt_status() -> dict:
    """Whether voice input can work, and why not if it cannot."""
    if importlib.util.find_spec("faster_whisper") is None:
        return {"available": False, "reason": "faster-whisper is not installed"}
    try:
        import sounddevice as sd
        sd.check_input_settings(samplerate=SAMPLE_RATE, channels=1)
    except ImportError:
        return {"available": False, "reason": "sounddevice is not installed"}
    except Exception as exc:
        return {"available": False, "reason": f"no usable microphone ({exc})"}
    return {"available": True, "reason": ""}


def warm_up() -> None:
    """Load the speech model ahead of time so the first spoken question is not slow."""
    if stt_status()["available"]:
        try:
            _load_whisper()
        except VoiceError as exc:
            print(exc)
