"""Build or refresh the code database from data/dtc_codes.json.

The app does this automatically every time it starts. Run this file by hand
when you want to check that a code you just added is valid:

    python init_db.py
"""
import sys

import db

if __name__ == "__main__":
    try:
        count = db.init_db()
    except ValueError as exc:
        sys.exit(f"Problem in {db.SEED_PATH.name}: {exc}")
    print(f"Database ready with {count} codes: {db.DB_PATH}")
