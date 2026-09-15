"""FastAPI routes for the Autonomous Job Agent."""

from __future__ import annotations

import os
import re
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import brain
import output
import scout


app = FastAPI(title="Autonomous Job Agent")

DEFAULT_MATCH_THRESHOLD = int(os.getenv("MATCH_SCORE_THRESHOLD", "75"))


class HuntRequest(BaseModel):
    keywords: str = Field(default="Full Stack Developer")
    location: str = Field(default="Karachi")
    master_resume: str | None = None
    resume_bullets: list[str] | None = None
    min_match_score: int = Field(default=DEFAULT_MATCH_THRESHOLD, ge=0, le=100)


class JobResult(BaseModel):
    company: str
    position: str
    match_score: int
    status: str
    job_url: str
    resume_link: str | None = None
    error: str | None = None


class HuntResponse(BaseModel):
    jobs_processed: int
    resumes_generated: int
    results: list[JobResult]


@app.get("/")
def health_check() -> dict[str, str]:
    return {"status": "Autonomous Job Agent is running"}


@app.post("/initiate-hunt", response_model=HuntResponse)
def initiate_hunt(request: HuntRequest) -> HuntResponse:
    """Scout jobs, analyze each match, and generate resumes for strong matches."""
    master_resume = _resolve_master_resume(request.master_resume)

    try:
        jobs = scout.get_jobs(request.keywords, request.location)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Scout failed: {exc}") from exc

    results: list[JobResult] = []
    resumes_generated = 0

    for job in jobs:
        company = job.get("company", "")
        position = job.get("title", "")
        job_url = job.get("jobUrl", "")
        description = job.get("descriptionText", "")

        try:
            analysis = brain.analyze_job(description, master_resume)
            match_score = _extract_match_score(analysis)

            if match_score <= request.min_match_score:
                results.append(
                    JobResult(
                        company=company,
                        position=position,
                        match_score=match_score,
                        status="Skipped - match score below threshold",
                        job_url=job_url,
                    )
                )
                continue

            tailored_resume = brain.generate_tailored_resume(
                job_description=description,
                master_resume=master_resume,
                resume_bullets=request.resume_bullets or master_resume,
            )
            pdf_text = _build_pdf_text(
                company=company,
                position=position,
                job_url=job_url,
                analysis=analysis,
                tailored_resume=tailored_resume,
            )
            pdf_path = output.create_pdf(
                pdf_text,
                filename=f"{company}_{position}_resume.pdf",
            )
            resume_link = output.upload_and_log(
                pdf_path=pdf_path,
                company=company,
                position=position,
                match_score=match_score,
                status="Ready",
            )
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


def _extract_match_score(analysis: str) -> int:
    match = re.search(r"match\s*score\s*:\s*(\d{1,3})", analysis, re.IGNORECASE)
    if not match:
        match = re.search(r"\b(\d{1,3})\s*/\s*100\b", analysis)
    if not match:
        return 0
    return max(0, min(100, int(match.group(1))))


def _resolve_master_resume(request_resume: str | None) -> str:
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


def _build_pdf_text(
    company: str,
    position: str,
    job_url: str,
    analysis: str,
    tailored_resume: str,
) -> str:
    sections: list[Any] = [
        f"Tailored Resume - {position}",
        f"Company: {company}",
        f"Job Link: {job_url}",
        "",
        "Recruiter Analysis",
        analysis,
        "",
        "Tailored Resume Content",
        tailored_resume,
    ]
    return "\n".join(str(section) for section in sections)
