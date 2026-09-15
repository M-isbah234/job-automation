"""PDF generation, Google Drive upload, and Google Sheets logging."""

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


load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
TEMP_DIR = BASE_DIR / "temp"
SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
]


def create_resume_pdf(resume_text: str, filename: str = "tailored_resume.pdf") -> Path:
    """Create a clean PDF in the temp folder and return its path."""
    try:
        from fpdf import FPDF
    except ImportError as exc:
        raise RuntimeError("fpdf2 is not installed. Run: pip install fpdf2") from exc

    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = TEMP_DIR / _safe_pdf_filename(filename)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)

    for line in resume_text.splitlines():
        clean_line = line.strip()
        if not clean_line:
            pdf.ln(5)
            continue
        pdf.multi_cell(0, 7, clean_line, new_x="LMARGIN", new_y="NEXT")

    pdf.output(str(pdf_path))
    return pdf_path


def create_pdf(resume_text: str, filename: str = "tailored_resume.pdf") -> Path:
    """Compatibility wrapper for the control tower workflow."""
    return create_resume_pdf(resume_text, filename)


def upload_pdf_to_drive(pdf_path: str | Path) -> str:
    """Upload a PDF to Google Drive and return a shareable link."""
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    service = build("drive", "v3", credentials=_get_google_credentials())
    file_metadata = {"name": path.name}
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
    """Append one application row to the configured Google Sheet."""
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
    if not sheet_id:
        raise RuntimeError("Missing GOOGLE_SHEET_ID in .env")

    values = [[
        row_date or date.today().isoformat(),
        company,
        position,
        str(match_score),
        resume_link,
        status,
    ]]

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
    """Create a Google Sheet dashboard and return its spreadsheet ID."""
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
    resume_link = upload_pdf_to_drive(pdf_path)
    append_application_row(
        company=company,
        position=position,
        match_score=match_score,
        resume_link=resume_link,
        status=status,
    )
    return resume_link


def _get_google_credentials() -> Credentials:
    token_file = Path(os.getenv("GOOGLE_TOKEN_FILE", "token.json"))
    client_secrets = os.getenv("GOOGLE_CLIENT_SECRETS_FILE", "").strip()

    credentials = None
    if token_file.exists():
        credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if credentials and credentials.valid:
        return credentials

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    else:
        if not client_secrets:
            raise RuntimeError("Missing GOOGLE_CLIENT_SECRETS_FILE in .env")
        flow = InstalledAppFlow.from_client_secrets_file(client_secrets, SCOPES)
        credentials = flow.run_local_server(port=0)

    token_file.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


def _safe_pdf_filename(filename: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename).strip("._")
    if not safe_name:
        safe_name = "tailored_resume.pdf"
    if not safe_name.lower().endswith(".pdf"):
        safe_name += ".pdf"
    return safe_name
