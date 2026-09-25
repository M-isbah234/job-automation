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


class _ResumePDFBuilder:
    """PDF builder that renders resumes matching the candidate's exact master layout and styling."""

    def __init__(self):
        from fpdf import FPDF
        self.pdf = FPDF(orientation="P", unit="mm", format="A4")
        self.pdf.set_auto_page_break(auto=True, margin=14)
        self.font_name = "Helvetica"
        self.has_unicode_font = False

        # Attempt to load Arial TTF for full Unicode bullet and em-dash rendering
        font_paths = [
            ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/ariali.ttf"),
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", None),
        ]
        for reg, bold, italic in font_paths:
            if os.path.exists(reg):
                self.pdf.add_font("CustomFont", "", reg)
                if bold and os.path.exists(bold):
                    self.pdf.add_font("CustomFont", "B", bold)
                if italic and os.path.exists(italic):
                    self.pdf.add_font("CustomFont", "I", italic)
                self.font_name = "CustomFont"
                self.has_unicode_font = True
                break

    def sanitize(self, text: str) -> str:
        if self.has_unicode_font:
            return text
        # If fallback Helvetica, convert Unicode characters cleanly to Latin-1
        text = text.replace("●", chr(149)).replace("•", chr(149))
        text = text.replace("—", "-").replace("–", "-")
        text = text.replace('“', '"').replace('”', '"').replace("’", "'").replace("‘", "'")
        return text.encode("latin-1", "replace").decode("latin-1")

    def render(self, raw_text: str, output_path: str | Path) -> None:
        self.pdf.set_margins(15, 12, 15)
        self.pdf.add_page()

        lines = [line.strip() for line in raw_text.splitlines()]

        # Skip empty leading lines
        idx = 0
        while idx < len(lines) and not lines[idx]:
            idx += 1

        if idx >= len(lines):
            self.pdf.output(str(output_path))
            return

        # 1. Candidate Name (Header)
        name = lines[idx]
        idx += 1
        self.pdf.set_font(self.font_name, "B", 17)
        self.pdf.set_text_color(17, 24, 39)
        self.pdf.cell(0, 8, self.sanitize(name), align="C", new_x="LMARGIN", new_y="NEXT")

        # 2. Contact details line (email, linkedin, github)
        if idx < len(lines) and lines[idx]:
            contact_line = lines[idx]
            idx += 1
            self.pdf.set_font(self.font_name, "", 8.5)
            self.pdf.set_text_color(71, 85, 105)
            self.pdf.cell(0, 5, self.sanitize(contact_line), align="C", new_x="LMARGIN", new_y="NEXT")
            self.pdf.ln(3)

        section_names = {
            "SUMMARY", "SKILLS", "EXPERIENCE / INTERNSHIP", "EXPERIENCE",
            "INTERNSHIP", "PROJECTS", "EDUCATION", "CERTIFICATES", "CERTIFICATIONS"
        }

        # 3. Main Resume Body
        while idx < len(lines):
            line = lines[idx]
            idx += 1
            if not line:
                self.pdf.ln(2)
                continue

            upper_line = line.upper().strip()

            # Section heading
            if upper_line in section_names or (len(line) < 30 and any(upper_line.startswith(s) for s in section_names)):
                self.pdf.ln(3)
                self.pdf.set_font(self.font_name, "B", 12)
                self.pdf.set_text_color(15, 23, 42)
                self.pdf.cell(0, 6, self.sanitize(line), new_x="LMARGIN", new_y="NEXT")
                self.pdf.set_draw_color(226, 232, 240)
                self.pdf.line(15, self.pdf.get_y(), 195, self.pdf.get_y())
                self.pdf.ln(2)
                continue

            # Bullet points
            is_bullet = line.startswith(("●", "•", "-", "*"))
            if is_bullet:
                bullet_body = re.sub(r"^[●•\-\*]\s*", "", line).strip()
                self.pdf.set_text_color(30, 41, 59)
                prefix_match = re.match(r"^([^:]{2,35}:)\s*(.*)", bullet_body)
                bullet_char = "● " if self.has_unicode_font else chr(149) + " "

                bullet_x = 18
                content_x = 22
                content_w = 195 - content_x

                self.pdf.set_x(bullet_x)
                self.pdf.set_font(self.font_name, "", 8.5)
                self.pdf.write(5, self.sanitize(bullet_char))

                self.pdf.set_x(content_x)
                if prefix_match:
                    prefix, rest = prefix_match.groups()
                    self.pdf.set_font(self.font_name, "B", 9.5)
                    self.pdf.write(5, self.sanitize(prefix + " "))
                    self.pdf.set_font(self.font_name, "", 9.5)
                    self.pdf.multi_cell(content_w, 5, self.sanitize(rest), new_x="LMARGIN", new_y="NEXT")
                else:
                    self.pdf.set_font(self.font_name, "", 9.5)
                    self.pdf.multi_cell(content_w, 5, self.sanitize(bullet_body), new_x="LMARGIN", new_y="NEXT")
                continue

            # Role / Company / Project title header (e.g. Decode Labs | AI Engineering Intern)
            if "|" in line and len(line) < 100:
                self.pdf.ln(1.5)
                self.pdf.set_font(self.font_name, "B", 10.5)
                self.pdf.set_text_color(17, 24, 39)
                self.pdf.cell(0, 5, self.sanitize(line), new_x="LMARGIN", new_y="NEXT")
                continue

            # Date / Location line
            if any(term in line for term in ["202", "201", "Remote", "Pakistan", "Karachi", "–", "—"]) and len(line) < 80:
                self.pdf.set_font(self.font_name, "I", 9)
                self.pdf.set_text_color(100, 116, 139)
                self.pdf.cell(0, 4.5, self.sanitize(line), new_x="LMARGIN", new_y="NEXT")
                continue

            # Standard paragraph line (Summary description, etc.)
            self.pdf.set_font(self.font_name, "", 9.5)
            self.pdf.set_text_color(51, 65, 85)
            self.pdf.multi_cell(0, 5, self.sanitize(line), new_x="LMARGIN", new_y="NEXT")

        self.pdf.output(str(output_path))


def create_resume_pdf(resume_text: str, filename: str = "tailored_resume.pdf") -> Path:
    """Create a professionally styled ATS resume PDF adhering to the master resume pattern.

    Args:
        resume_text: Clean plain text content of the complete tailored resume.
        filename: Target filename for the generated PDF document.

    Returns:
        Path object pointing to the created PDF file.
    """
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = TEMP_DIR / _safe_pdf_filename(filename)
    builder = _ResumePDFBuilder()
    builder.render(resume_text, pdf_path)
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
    job_url: str,
    status: str = "Ready",
    row_date: str | None = None,
) -> None:
    """Append one application row to the configured Google Sheet.

    Args:
        company: Target company name.
        position: Job title / role.
        match_score: Numerical match score calculated by Gemini.
        resume_link: Google Drive link to the tailored PDF.
        job_url: Link to the original job posting.
        status: Application status (default 'Ready').
        row_date: Optional ISO date string; defaults to current date.
    """
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
    if not sheet_id:
        raise RuntimeError("Missing GOOGLE_SHEET_ID in .env")

    # Format values matching dashboard headers: Date, Company, Position, Match Score, Link, Status, Job Link
    values = [[
        row_date or date.today().isoformat(),
        company,
        position,
        str(match_score),
        resume_link,
        status,
        job_url,
    ]]

    # Build authenticated Google Sheets v4 client and append the row
    service = build("sheets", "v4", credentials=_get_google_credentials())
    service.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range=os.getenv("GOOGLE_SHEET_RANGE", "Sheet1!A:G"),
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
        range=os.getenv("GOOGLE_SHEET_HEADER_RANGE", "Sheet1!A1:G1"),
        valueInputOption="USER_ENTERED",
        body={
            "values": [[
                "Date",
                "Company",
                "Position",
                "Match Score",
                "Resume Link",
                "Status",
                "Job Link",
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
    job_url: str,
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
        job_url=job_url,
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

