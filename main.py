"""FastAPI routes and pipeline orchestration for the Autonomous Job Agent.

This module acts as the application's control tower:
1. Exposes REST API endpoints for health monitoring and triggering job hunts.
2. Defines strict Pydantic validation schemas for incoming requests and responses.
3. Coordinates the pipeline: Scout (Apify) -> Brain (Gemini) -> Output (PDF, Drive, Sheets).
4. Provides robust error isolation per job item to ensure batch resilience.
"""

from __future__ import annotations

import io
import os
import re
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import brain
import output
import scout

# Initialize FastAPI application instance
app = FastAPI(
    title="Autonomous Job Agent",
    description="Automated LinkedIn job search, AI resume tailoring, and tracking pipeline.",
    version="1.0.0",
)

# Minimum match score required to generate tailored resume (default 75%)
DEFAULT_MATCH_THRESHOLD = int(os.getenv("MATCH_SCORE_THRESHOLD", "75"))


# --- Pydantic Data Validation Models ---

class HuntRequest(BaseModel):
    """Payload schema for initiating an autonomous job hunt."""
    keywords: str = Field(default="Full Stack Developer", description="Target job title or keywords")
    location: str = Field(default="Karachi", description="Target geographic location or 'Remote'")
    master_resume: str | None = Field(default=None, description="Optional raw resume text override")
    resume_bullets: list[str] | None = Field(default=None, description="Optional bullet points to tailor")
    min_match_score: int = Field(
        default=DEFAULT_MATCH_THRESHOLD,
        ge=0,
        le=100,
        description="Minimum score (0-100) to trigger resume generation",
    )
    max_jobs: int = Field(default=10, description="Max jobs to scrape")


class JobResult(BaseModel):
    """Status report model for each scraped and processed job posting."""
    company: str
    position: str
    match_score: int
    status: str
    job_url: str
    resume_link: str | None = None
    error: str | None = None


class HuntResponse(BaseModel):
    """Summary response returned after job hunt pipeline execution."""
    jobs_processed: int
    resumes_generated: int
    results: list[JobResult]


class ResumeUpdatePayload(BaseModel):
    """Payload schema for updating master reference resume text."""
    content: str = Field(description="Full text of the master resume")


# --- API Endpoints ---

@app.get("/")
def serve_ui():
    """Serve the frontend UI."""
    return FileResponse("index.html")


@app.get("/api/resume")
def get_master_resume():
    """Fetch the current master resume text stored on the server."""
    try:
        content = _resolve_master_resume(None)
        return {"content": content, "status": "ok"}
    except HTTPException:
        return {"content": "", "status": "empty"}


@app.post("/api/resume")
def update_master_resume(payload: ResumeUpdatePayload):
    """Save updated master resume text to disk."""
    if not payload.content.strip():
        raise HTTPException(status_code=400, detail="Resume content cannot be empty.")
    _save_master_resume(payload.content.strip())
    return {"status": "ok", "message": "Master resume updated successfully."}


@app.post("/api/resume/upload")
async def upload_resume_file(file: UploadFile = File(...)):
    """Upload a resume file (.pdf or .txt), extract text, and update the reference resume."""
    filename = (file.filename or "").lower()
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    extracted_text = ""
    if filename.endswith(".pdf"):
        extracted_text = _extract_text_from_pdf(file_bytes)
    elif filename.endswith(".txt") or filename.endswith(".md"):
        try:
            extracted_text = file_bytes.decode("utf-8").strip()
        except UnicodeDecodeError:
            extracted_text = file_bytes.decode("latin-1", errors="ignore").strip()
    else:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file format. Please upload a .pdf or .txt file.",
        )

    if not extracted_text.strip():
        raise HTTPException(status_code=400, detail="Could not extract readable text from the file.")

    _save_master_resume(extracted_text.strip())
    return {
        "status": "ok",
        "message": f"Successfully extracted and saved {file.filename}",
        "content": extracted_text.strip(),
        "filename": file.filename,
    }


@app.get("/api/resume/preview-pdf")
def preview_master_resume_pdf():
    """Generate and return a rendered PDF of the current master resume."""
    content = _resolve_master_resume(None)
    pdf_path = output.create_pdf(content, filename="Master_Resume_Preview.pdf")
    return FileResponse(
        str(pdf_path),
        media_type="application/pdf",
        filename="Master_Resume_Preview.pdf",
    )


@app.post("/initiate-hunt", response_model=HuntResponse)
def initiate_hunt(request: HuntRequest) -> HuntResponse:
    """Scout jobs, analyze each match with Gemini, and generate tailored resumes for strong matches.

    Workflow per job:
    1. Scrapes matching postings using Apify LinkedIn Actor.
    2. Runs Gemini analysis on candidate fit and extracts numerical score.
    3. If score >= min_match_score, rewrites bullet points and creates PDF resume.
    4. Uploads PDF to Google Drive and logs the record in Google Sheets.
    """
    # Load candidate master resume (either passed in request or from disk)
    master_resume = _resolve_master_resume(request.master_resume)

    # Step 1: Scrape LinkedIn job postings via Scout module
    try:
        jobs = scout.get_jobs(request.keywords, request.location, request.max_jobs)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Scout failed: {exc}") from exc

    results: list[JobResult] = []
    resumes_generated = 0

    # Step 2: Iterate through all retrieved jobs with per-job error isolation
    print(f"Apify found {len(jobs)} jobs! Starting AI analysis...")
    for idx, job in enumerate(jobs, 1):
        company = job.get("company", "")
        position = job.get("title", "")
        job_url = job.get("jobUrl", "")
        description = job.get("descriptionText", "")
        
        print(f"[{idx}/{len(jobs)}] Analyzing {position} at {company}...")

        try:
            # 2a. Gemini evaluates candidate fit against job description
            analysis = brain.analyze_job(description, master_resume)
            match_score = _extract_match_score(analysis)

            # 2b. Skip generation if candidate fit is below threshold
            if match_score < request.min_match_score:
                results.append(
                    JobResult(
                        company=company,
                        position=position,
                        match_score=match_score,
                        status="Skipped - match score below threshold",
                        job_url=job_url,
                    )
                )
                print(f" -> Skipped (Score: {match_score})")
                continue

            # 2c. Gemini generates complete tailored resume matching original CV pattern
            tailored_resume = brain.generate_tailored_resume(
                job_description=description,
                master_resume=master_resume,
                resume_bullets=request.resume_bullets,
            )

            # 2d. Render PDF document locally adhering to ATS styling
            pdf_path = output.create_pdf(
                tailored_resume,
                filename=f"{company}_{position}_resume.pdf",
            )

            # 2e. Upload PDF to Drive & append row to Google Sheet
            resume_link = output.upload_and_log(
                pdf_path=pdf_path,
                company=company,
                position=position,
                match_score=match_score,
                status="Ready",
            )
            print(f" -> Generated PDF and uploaded to Drive! (Score: {match_score})")
            resumes_generated += 1

            results.append(
                JobResult(
                    company=company,
                    position=position,
                    match_score=match_score,
                    status="Ready",
                    job_url=job_url,
                    resume_link=resume_link,
                )
            )
        except Exception as exc:
            print(f" -> Error processing job: {exc}")
            # Catch individual job errors without aborting remaining jobs
            results.append(
                JobResult(
                    company=company,
                    position=position,
                    match_score=0,
                    status="Error",
                    job_url=job_url,
                    error=str(exc),
                )
            )

    return HuntResponse(
        jobs_processed=len(jobs),
        resumes_generated=resumes_generated,
        results=results,
    )


# --- Helper Functions ---

def _extract_match_score(analysis: str) -> int:
    """Parse integer match score from Gemini's plain text response using regex."""
    # Try pattern: Match Score: 85
    match = re.search(r"match\s*score\s*:\s*(\d{1,3})", analysis, re.IGNORECASE)
    if not match:
        # Try fallback pattern: 85/100
        match = re.search(r"\b(\d{1,3})\s*/\s*100\b", analysis)
    if not match:
        return 0
    # Clamp score between 0 and 100
    return max(0, min(100, int(match.group(1))))


def _resolve_master_resume(request_resume: str | None) -> str:
    """Resolve candidate resume from request body or fall back to default text file on disk."""
    if request_resume and request_resume.strip():
        return request_resume.strip()

    resume_file = os.getenv("MASTER_RESUME_FILE", "data/master_resume.txt")
    if not os.path.exists(resume_file):
        raise HTTPException(
            status_code=400,
            detail=f"Master resume file not found. Create it at {resume_file}.",
        )

    with open(resume_file, "r", encoding="utf-8") as file:
        master_resume = file.read().strip()

    if not master_resume:
        raise HTTPException(
            status_code=400,
            detail=f"Master resume is empty. Paste your resume into {resume_file}.",
        )
    return master_resume


def _save_master_resume(content: str) -> None:
    """Save content to the configured master resume file."""
    resume_file = os.getenv("MASTER_RESUME_FILE", "data/master_resume.txt")
    os.makedirs(os.path.dirname(os.path.abspath(resume_file)), exist_ok=True)
    with open(resume_file, "w", encoding="utf-8") as f:
        f.write(content.strip())


def _extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract clean plain text from uploaded PDF bytes."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        pages_text: list[str] = []
        for page in reader.pages:
            t = page.extract_text() or ""
            if t.strip():
                pages_text.append(t.strip())
        return "\n\n".join(pages_text)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to extract text from PDF: {exc}",
        ) from exc

