# AI Car Voice Assistant

A voice-powered assistant that explains car diagnostic trouble codes in plain English.
You say or type something like *"What does P0420 mean on my 2015 Honda Accord with 128k miles?"*
and it looks up verified facts, has a local AI model explain them for your car, and reads the
answer back to you.

Everything runs on your own computer. No subscriptions, no cloud, no fees.

This is the built and updated version of the "AI Car Voice Assistant: Complete Build Guide
(Prototype v2)". See [What changed from the guide](#what-changed-from-the-guide) for the fixes.

## How it works

1. You speak or type your question.
2. Speech-to-text (faster-whisper, running locally) turns your voice into text.
3. The app pulls the code, year, make, model and mileage out of the sentence.
4. It looks up verified facts for that code in a local SQLite database.
5. It sends those facts to a local AI model through Ollama and asks for a short explanation.
6. The page shows a result card and reads the answer aloud.
7. You can ask follow-up questions about the same car and code.

The AI is never asked to guess. Severity, safety, causes, checks and repair costs on the card
come straight from the database. The model only writes the summary, the advice and the spoken
answer, and it is told to use nothing but those facts. If a code is not in the database the
app says so instead of inventing an answer.

If Ollama is not running, the app still works: it answers directly from the verified facts
and tells you the AI model was not used.

## What you need

| Thing | What it does | Cost |
|---|---|---|
| A computer (Windows, Mac or Linux) | Runs everything locally | Free |
| Python 3.10 or newer | Runs the app | Free |
| Ollama + the `llama3.2:3b` model (about 2 GB) | The local AI model | Free |
| A microphone | Voice input (optional, you can type instead) | Built into most laptops |

## Setup

### 1. Install Python

Download Python from [python.org](https://www.python.org/downloads/). On Windows, tick
**"Add Python to PATH"** in the installer. Check it in a terminal:

```
python --version
```

### 2. Install Ollama and the AI model

Download Ollama from [ollama.com](https://ollama.com/download), install it, then in a new terminal:

```
ollama pull llama3.2:3b
```

### 3. Start the app

The quick way: double-click **`run.bat`** on Windows, or run `./run.sh` on Mac or Linux.
The first run creates the virtual environment and installs the packages, which takes a few
minutes. After that it starts the app and opens the page in your browser.

To do the same steps by hand, open a terminal in the project folder.

Windows:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Mac or Linux:

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Linux, voice also needs two system packages: `sudo apt install libportaudio2 espeak-ng`.

Run the activate command again every time you open a new terminal for this project.

Then start the app:

```
python app.py
```

Your browser opens <http://127.0.0.1:8000> automatically.

The pills at the top of the page show what is working: the AI model, the microphone, and how
many codes are loaded. The first time you use voice, the speech model (about 75 MB) downloads
once. After that no internet connection is needed.

## Your first test

**By voice:** click **Speak your question**, say *"P0420 on a 2015 Honda Accord with 128,000 miles"*,
then stop talking. The app stops listening when you pause, fills in the form, shows the answer
card and reads it aloud. Then ask a follow-up such as *"Is it safe to drive to work?"*

**By typing:** enter `P0420`, `2015`, `Honda`, `Accord`, `128000` and click **Explain this code**.
Only the code is required.

The verified facts (safe to drive, cost, causes) appear straight away. The AI's summary for
your car fills in a few seconds later and is then read aloud.

**Several codes at once:** say or type them together, for example `P0420, P0300`. The app
explains the most serious one first, lists the others as buttons, and tells the AI about all
of them, because codes that appear together often share one cause.

## Adding more codes

The database starts with 54 common codes in [`data/dtc_codes.json`](data/dtc_codes.json).
To add one, copy an existing entry, change the fields, and restart the app:

```json
{
  "code": "P0128",
  "title": "Coolant Temperature Below Thermostat Regulating Temperature",
  "plain_english": "The engine is staying cooler than it should, or taking too long to warm up.",
  "severity": "low",
  "safe_to_drive": "Usually yes, but repair soon.",
  "common_causes": ["thermostat stuck open", "low coolant level"],
  "next_checks": ["check the coolant level with the engine cold"],
  "repair_min": 120,
  "repair_max": 450,
  "misdiagnosis_notes": "Check thermostat behavior before replacing the sensor.",
  "high_mileage_note": "Optional. Shown only when the car has 100,000 miles or more."
}
```

`severity` must be `low`, `moderate`, `high` or `critical`. Run `python init_db.py` to check
your edit: it reports the code and field if something is wrong.

The starter facts and cost ranges are general guidance written for this prototype. Check them
against a trusted source (a factory service manual, iATN, or a mechanic you trust) before
relying on them, and do the same for codes you add.

## Settings

Set these environment variables before starting the app if you want to change a default.

| Variable | Default | What it does |
|---|---|---|
| `OLLAMA_MODEL` | `llama3.2:3b` | Which Ollama model to use |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Where Ollama is running |
| `WHISPER_MODEL` | `base.en` | Speech model. `small.en` is more accurate and slower |
| `PORT` | `8000` | Port for the web page |
| `HOST` | `127.0.0.1` | Set to `0.0.0.0` to open the page from a phone on the same Wi-Fi |
| `ALLOWED_HOSTS` | (none) | Extra names the app answers to, such as `garage-pc.local` |
| `NO_BROWSER` | (none) | Set to `1` to stop the browser opening automatically |

On a phone, open the page by the computer's IP address, for example `http://192.168.1.20:8000`.

From a phone, typing and spoken answers work. The **Speak** button uses the microphone of the
computer running the app, not the phone's.

## Troubleshooting

| Problem | Likely cause | Fix |
|---|---|---|
| `python` is not recognized | PATH not set during install | Reinstall Python and tick "Add Python to PATH" |
| Pill says "AI offline: facts only" | Ollama is not running | Start Ollama, then reload the page |
| Pill says "AI model not downloaded" | Model not pulled | `ollama pull llama3.2:3b` |
| Pill says "No microphone" | No mic, or a voice package is missing | Hover over the pill for the reason. Check mic permissions in your system settings |
| "I did not hear anything" | Wrong input device or mic muted | Set the right default microphone in your system sound settings |
| No spoken answer | Browser has no voices, or sound is muted | Switch "Read answers aloud" to the other option |
| "I do not have verified facts for …" | Code is not in the database | Add it to `data/dtc_codes.json` and restart |
| Port 8000 in use | Another app is using it | Start with a different `PORT` |
| A package fails to install | Voice packages on an unusual system | The app still runs with typed input. Install the first four lines of `requirements.txt` by themselves |

## Project layout

```
app.py              the web app and its API
db.py               SQLite: code facts and lookup history
llm.py              talks to Ollama; builds facts-only answers when it is offline
parsing.py          finds the code and vehicle details in a sentence
voice_handler.py    microphone recording, speech-to-text, text-to-speech
init_db.py          checks and rebuilds the database by hand
run.bat / run.sh    one-step setup and start
data/dtc_codes.json the verified code facts (edit this to add codes)
static/index.html   the web page
tests/              automated tests
```

To run the tests: `pip install -r requirements-dev.txt` then `python -m pytest`.

## What changed from the guide

Fixes to problems in the original guide's code:

- **Voice input needed ffmpeg and would crash without it.** `openai-whisper` shells out to
  ffmpeg to read the recorded file, and the guide never installs it. The app now uses
  faster-whisper and passes the audio straight from memory. That also removes the roughly
  2 GB PyTorch download and transcribes faster on a laptop.
- **Pinned packages did not install on current Python.** Versions are now minimums instead of
  old exact pins.
- **Overlapping spoken answers crashed or hung.** Each answer started a new speech engine in a
  new thread. Speech now goes through one worker, and by default the browser does the talking.
- **The app would not start without every voice package.** Voice parts now load only when used,
  so typed input always works.
- **Only two of the eight promised starter codes were in the file.** There are now 54.
- **Follow-up answers were inserted into the page as raw HTML.** Everything from the model is
  now inserted as plain text.
- **Any website open in your browser could trigger the microphone.** Cross-site requests are
  now refused, and the app only answers to `localhost` or an IP address.
- **The model could invent prices and causes.** Those fields now come only from the database,
  and the model's reply is forced into a fixed JSON shape.
- **Malformed model output caused a server error.** The app now falls back to a facts-only answer.
- **Follow-ups shared one global "session"** across every browser tab. The page now carries its
  own conversation.
- **The follow-up endpoint froze the whole server** while recording and thinking.
- **Voice only filled in the code and year.** It now also picks up make, model and mileage, and
  understands codes that speech-to-text splits up ("P zero four twenty", "P 0 4 2 0").

Improvements:

- Recording stops when you stop talking instead of after a fixed 8 seconds.
- The verified facts appear instantly; you no longer wait for the AI to see whether the car
  is safe to drive.
- Several codes can be explained together, most serious first.
- One-step launchers (`run.bat`, `run.sh`), and both models load in the background at startup
  so the first question is not slow.
- The assistant stops talking when you press the microphone, so it does not record itself.
- Works without Ollama, answering from the verified facts.
- Mileage-aware notes for cars over 100,000 miles (Phase 4 in the guide).
- Remembers past lookups and mentions earlier codes for the same car (Phase 5).
- Phone-friendly page with dark mode (part of Phase 6).
- Typed follow-up questions, a "read aloud again" button, and status indicators.
- Codes that are not in the database get a plain explanation of what the letter and digits
  mean, without guessing at the fault.
- Runs on Windows, Mac and Linux.

## What to build next

| Phase | What to add |
|---|---|
| Next | Bluetooth OBD scanner (ELM327) so the app reads codes from the car itself |
| Then | Wake word, so the assistant starts when you say "Hey car" |
| Then | Use the phone's own microphone (needs HTTPS on the local network) |
| Later | A larger model for richer explanations once hardware allows |

## Reality check

This prototype shows that a local assistant can explain car codes in plain English and talk
with a driver about them, for free. It is not a complete product and it does not replace a
mechanic. Treat its answers as a starting point, especially for anything safety-related.
