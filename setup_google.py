"""Initialize Google OAuth and write Google Sheet headers."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from output import create_application_sheet, initialize_sheet_headers


ENV_PATH = Path(".env")


if __name__ == "__main__":
    load_dotenv()

    sheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
    if not sheet_id:
        sheet_id = create_application_sheet()
        _env_text = ENV_PATH.read_text(encoding="utf-8")
        _env_text = _env_text.replace("GOOGLE_SHEET_ID=", f"GOOGLE_SHEET_ID={sheet_id}")
        ENV_PATH.write_text(_env_text, encoding="utf-8")
        os.environ["GOOGLE_SHEET_ID"] = sheet_id
        print(f"Created Google Sheet: {sheet_id}")

    initialize_sheet_headers()
    print("Google auth connected and sheet headers initialized.")
