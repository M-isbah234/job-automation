"""Initialize Google OAuth and write Google Sheet headers.

This setup utility script:
1. Loads current configuration from .env.
2. Triggers Google OAuth2 flow via browser if valid token does not exist.
3. Checks if GOOGLE_SHEET_ID is already configured:
   - If missing, automatically creates a new Google Sheet on the authenticated account
     and writes its ID back into the local .env file.
4. Initializes the column headers (Date, Company, Position, Match Score, Resume Link, Status).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from output import create_application_sheet, initialize_sheet_headers

# Path to the local environment configuration file
ENV_PATH = Path(".env")


if __name__ == "__main__":
    # Load existing environment variables
    load_dotenv()

    # Verify or provision the application tracking spreadsheet
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
    if not sheet_id:
        # Create a new spreadsheet on Google Drive
        sheet_id = create_application_sheet()

        # Persist the newly generated sheet ID into the .env file
        _env_text = ENV_PATH.read_text(encoding="utf-8")
        _env_text = _env_text.replace("GOOGLE_SHEET_ID=", f"GOOGLE_SHEET_ID={sheet_id}")
        ENV_PATH.write_text(_env_text, encoding="utf-8")
        os.environ["GOOGLE_SHEET_ID"] = sheet_id
        print(f"Created Google Sheet: {sheet_id}")

    # Write column headers to Row 1 of Sheet1
    initialize_sheet_headers()
    print("Google auth connected and sheet headers initialized.")

