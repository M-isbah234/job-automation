"""PDF generation, Google Drive upload, and Google Sheets logging.

This module is responsible for the output and export pipeline:
1. Converting tailored resume text into standardized, professional PDF files via fpdf2.
2. Uploading PDFs to Google Drive with automated public read permissions.
3. Logging job applications to a centralized Google Sheet dashboard for tracking.
4. Managing OAuth2 credentials and token caching for Google Workspace APIs.
"""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Load environment configuration
load_dotenv()

# Base directories and Google API scopes
BASE_DIR = Path(__file__).resolve().parent
TEMP_DIR = BASE_DIR / "temp"

# Minimal required scopes for Drive file management and Sheets editing
SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
]


def create_resume_pdf(resume_text: str, filename: str = "tailored_resume.pdf") -> Path:
    """Create a clean PDF in the temp folder and return its local file path.

    Args:
        resume_text: Plain text content of the resume, analysis, and job info.
        filename: Target filename for the generated PDF document.

    Returns:
        Path object pointing to the created PDF file.

    Raises:
        RuntimeError: If fpdf2 is not installed in the current environment.
    """
    try:
        from fpdf import FPDF
    except ImportError as exc:
        raise RuntimeError("fpdf2 is not installed. Run: pip install fpdf2") from exc

    # Ensure local temporary storage directory exists
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = TEMP_DIR / _safe_pdf_filename(filename)

    # Initialize FPDF with portrait orientation and standard margins
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)

    # Render each line with auto-wrapping to prevent text cutoff
    for line in resume_text.splitlines():
        clean_line = line.strip()
        if not clean_line:
            pdf.ln(5)  # Add paragraph spacing for empty lines
            continue
        pdf.multi_cell(0, 7, clean_line, new_x="LMARGIN", new_y="NEXT")

    # Save generated PDF to disk
    pdf.output(str(pdf_path))
    return pdf_path


def create_pdf(resume_text: str, filename: str = "tailored_resume.pdf") -> Path:
    """Compatibility wrapper for the control tower workflow."""
    return create_resume_pdf(resume_text, filename)


def upload_pdf_to_drive(pdf_path: str | Path) -> str:
    """Upload a PDF to Google Drive and return a shareable link.

    Args:
        pdf_path: Local path to the PDF file.

    Returns:
        Direct web view URL of the uploaded Google Drive document.

    Raises:
        FileNotFoundError: If the specified PDF file does not exist locally.
    """
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    # Build authenticated Google Drive v3 service client
    service = build("drive", "v3", credentials=_get_google_credentials())
    file_metadata = {"name": path.name}

    # If an explicit Google Drive folder ID is set, place file inside it
    folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip()
    if folder_id:
        file_metadata["parents"] = [folder_id]

    media = MediaFileUpload(str(path), mimetype="application/pdf", resumable=False)
    uploaded_file = (
        service.files()
        .create(
            body=file_metadata,
            media_body=media,
            fields="id, webViewLink",
        )
        .execute()
    )

    # Set shareable view permissions so recruiters/users can access the link
    service.permissions().create(
        fileId=uploaded_file["id"],
        body={"type": "anyone", "role": "reader"},
        fields="id",
    ).execute()

    return uploaded_file["webViewLink"]


def append_application_row(
    company: str,
    position: str,
    match_score: int | str,
    resume_link: str,
    status: str = "Ready",
    row_date: str | None = None,
) -> None:
    """Append one application row to the configured Google Sheet.

    Args:
        company: Target company name.
        position: Job title / role.
        match_score: Numerical match score calculated by Gemini.
        resume_link: Google Drive link to the tailored PDF.
        status: Application status (default 'Ready').
        row_date: Optional ISO date string; defaults to current date.
    """
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
    if not sheet_id:
        raise RuntimeError("Missing GOOGLE_SHEET_ID in .env")

    # Format values matching dashboard headers: Date, Company, Position, Match Score, Link, Status
    values = [[
        row_date or date.today().isoformat(),
        company,
        position,
        str(match_score),
        resume_link,
        status,
    ]]

    # Build authenticated Google Sheets v4 client and append the row
    service = build("sheets", "v4", credentials=_get_google_credentials())
    service.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range=os.getenv("GOOGLE_SHEET_RANGE", "Sheet1!A:F"),
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": values},
    ).execute()


def initialize_sheet_headers() -> None:
    """Write the application dashboard headers into the configured Google Sheet."""
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
    if not sheet_id:
        raise RuntimeError("Missing GOOGLE_SHEET_ID in .env")

    # Insert standardized column titles at the top of the worksheet
    service = build("sheets", "v4", credentials=_get_google_credentials())
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=os.getenv("GOOGLE_SHEET_HEADER_RANGE", "Sheet1!A1:F1"),
        valueInputOption="USER_ENTERED",
        body={
            "values": [[
                "Date",
                "Company",
                "Position",
                "Match Score",
                "Resume Link",
                "Status",
            ]]
        },
    ).execute()


def create_application_sheet(title: str = "Autonomous Job Agent Dashboard") -> str:
    """Create a new Google Sheet dashboard and return its spreadsheet ID."""
    service = build("sheets", "v4", credentials=_get_google_credentials())
    spreadsheet = (
        service.spreadsheets()
        .create(
            body={
                "properties": {"title": title},
                "sheets": [{"properties": {"title": "Sheet1"}}],
            },
            fields="spreadsheetId,spreadsheetUrl",
        )
        .execute()
    )
    return spreadsheet["spreadsheetId"]


def upload_and_log(
    pdf_path: str | Path,
    company: str,
    position: str,
    match_score: int | str,
    status: str = "Ready",
) -> str:
    """Upload a resume PDF to Drive, log the application in Sheets, and return the link."""
    # Step 1: Upload PDF and obtain shareable Drive link
    resume_link = upload_pdf_to_drive(pdf_path)

    # Step 2: Append record to tracking spreadsheet
    append_application_row(
        company=company,
        position=position,
        match_score=match_score,
        resume_link=resume_link,
        status=status,
    )
    return resume_link


def _get_google_credentials() -> Credentials:
    """Retrieve existing cached credentials, refresh if expired, or launch OAuth flow."""
    token_file = Path(os.getenv("GOOGLE_TOKEN_FILE", "token.json"))
    client_secrets = os.getenv("GOOGLE_CLIENT_SECRETS_FILE", "").strip()

    credentials = None
    # Check if a previously authorized token file is saved locally
    if token_file.exists():
        credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    # Return valid credentials directly
    if credentials and credentials.valid:
        return credentials

    # Refresh token if expired but refresh token exists
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    else:
        # Launch browser OAuth2 consent flow using client secrets JSON
        if not client_secrets:
            raise RuntimeError("Missing GOOGLE_CLIENT_SECRETS_FILE in .env")
        flow = InstalledAppFlow.from_client_secrets_file(client_secrets, SCOPES)
        credentials = flow.run_local_server(port=0)

    # Cache token credentials locally for subsequent runs
    token_file.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


def _safe_pdf_filename(filename: str) -> str:
    """Sanitize string to produce a safe filesystem filename with .pdf extension."""
    # Replace special characters and spaces with underscores
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename).strip("._")
    if not safe_name:
        safe_name = "tailored_resume.pdf"
    if not safe_name.lower().endswith(".pdf"):
        safe_name += ".pdf"
    return safe_name

