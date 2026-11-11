"""SQLite storage: verified code facts plus a history of past lookups."""
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
SEED_PATH = BASE_DIR / "data" / "dtc_codes.json"
DB_PATH = Path(os.environ.get("CAR_AI_DB", BASE_DIR / "data" / "car_ai.db"))

HIGH_MILEAGE = 100_000
LIST_FIELDS = ("common_causes", "next_checks")
REQUIRED = (
    "code", "title", "plain_english", "severity", "safe_to_drive",
    "common_causes", "next_checks", "repair_min", "repair_max", "misdiagnosis_notes",
)
SEVERITIES = ("low", "moderate", "high", "critical")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_seed(path: Path = SEED_PATH) -> list[dict]:
    """Read and validate the code facts file. Raises ValueError on a bad row."""
    rows = json.loads(path.read_text(encoding="utf-8"))
    for row in rows:
        label = row.get("code", "<missing code>")
        missing = [k for k in REQUIRED if k not in row]
        if missing:
            raise ValueError(f"{label}: missing field(s) {', '.join(missing)}")
        if row["severity"] not in SEVERITIES:
            raise ValueError(f"{label}: severity must be one of {', '.join(SEVERITIES)}")
        for field in LIST_FIELDS:
            if not isinstance(row[field], list) or not row[field]:
                raise ValueError(f"{label}: {field} must be a non-empty list")
        if row["repair_min"] > row["repair_max"]:
            raise ValueError(f"{label}: repair_min is larger than repair_max")
    return rows


def init_db() -> int:
    """Create tables and load every code from the facts file. Safe to re-run."""
    rows = load_seed()
    with closing(_connect()) as conn, conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS dtc_facts (
            code TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            plain_english TEXT NOT NULL,
            severity TEXT NOT NULL,
            safe_to_drive TEXT NOT NULL,
            common_causes TEXT NOT NULL,
            next_checks TEXT NOT NULL,
            repair_min INTEGER NOT NULL,
            repair_max INTEGER NOT NULL,
            misdiagnosis_notes TEXT NOT NULL,
            high_mileage_note TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS lookups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            year INTEGER,
            make TEXT,
            model TEXT,
            mileage INTEGER,
            code TEXT NOT NULL
        )""")
        conn.execute("DELETE FROM dtc_facts")
        conn.executemany(
            """INSERT INTO dtc_facts VALUES (:code, :title, :plain_english, :severity,
               :safe_to_drive, :common_causes, :next_checks, :repair_min, :repair_max,
               :misdiagnosis_notes, :high_mileage_note)""",
            [
                {
                    **row,
                    "code": row["code"].upper(),
                    "common_causes": json.dumps(row["common_causes"]),
                    "next_checks": json.dumps(row["next_checks"]),
                    "high_mileage_note": row.get("high_mileage_note"),
                }
                for row in rows
            ],
        )
    return len(rows)


def get_fact(code: str) -> Optional[dict]:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT * FROM dtc_facts WHERE code = ?", (code.strip().upper(),)
        ).fetchone()
    if row is None:
        return None
    fact = dict(row)
    for field in LIST_FIELDS:
        fact[field] = json.loads(fact[field])
    return fact


def list_codes() -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT code, title FROM dtc_facts ORDER BY code").fetchall()
    return [dict(r) for r in rows]


def known_codes() -> set[str]:
    return {r["code"] for r in list_codes()}


def mileage_note(fact: dict, mileage: Optional[int]) -> Optional[str]:
    """The high-mileage note for this code, if the car has enough miles for it to apply."""
    if mileage is not None and mileage >= HIGH_MILEAGE:
        return fact.get("high_mileage_note")
    return None


def previous_codes(vehicle: dict, code: str) -> list[str]:
    """Other codes looked up earlier for the same year, make and model."""
    if not (vehicle.get("year") and vehicle.get("make") and vehicle.get("model")):
        return []
    with closing(_connect()) as conn:
        rows = conn.execute(
            """SELECT code FROM lookups
               WHERE year = ? AND lower(make) = lower(?) AND lower(model) = lower(?)
                 AND code != ?
               GROUP BY code ORDER BY max(id) DESC LIMIT 5""",
            (vehicle["year"], vehicle["make"], vehicle["model"], code),
        ).fetchall()
    return [r["code"] for r in rows]


def record_lookup(vehicle: dict, code: str) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO lookups (year, make, model, mileage, code) VALUES (?, ?, ?, ?, ?)",
            (vehicle.get("year"), vehicle.get("make"), vehicle.get("model"),
             vehicle.get("mileage"), code),
        )


def recent_lookups(limit: int = 8) -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            """SELECT l.year, l.make, l.model, l.mileage, l.code, f.title, max(l.id) AS id
               FROM lookups l JOIN dtc_facts f ON f.code = l.code
               GROUP BY l.year, lower(l.make), lower(l.model), l.code
               ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
