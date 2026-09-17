"""Gemini AI logic for resume matching and tailoring.

This module powers the cognitive decision-making layer of the job agent.
It leverages the Google GenAI SDK to:
1. Analyze candidate resumes against scraped job descriptions, calculating a 0-100 match score.
2. Synthesize a targeted executive summary.
3. Rewrite bullet points with job-specific keywords for ATS (Applicant Tracking System) optimization.
"""

from __future__ import annotations

import os
import re

from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load API credentials and configuration from .env
load_dotenv()

# Select default Gemini model (optimized for speed and quality)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def analyze_job(job_description: str, master_resume: str) -> str:
    """Compare a resume with a job description and return plain-text analysis.

    Evaluates qualifications, skills overlap, and seniority match, returning
    a structured Match Score out of 100 alongside an aligned summary.

    Args:
        job_description: Full text of the employer's job posting.
        master_resume: Candidate's baseline resume text.

    Returns:
        Formatted plain text containing the Match Score and Professional Summary.
    """
    # System prompt enforcing strict structured plain-text formatting for downstream parsing
    prompt = (
        "You are an expert recruiter. Compare this resume to this job description.\n"
        "Return a Match Score from 0 to 100 and a tailored Professional Summary.\n"
        "The summary must be written for the candidate's resume and aligned with the job.\n\n"
        "Output format exactly:\n"
        "Match Score: <number>/100\n"
        "Professional Summary:\n"
        "<plain text summary>\n\n"
        "Do not use markdown, bold text, bullets, tables, or HTML.\n"
        "Return plain text only.\n\n"
        f"MASTER RESUME:\n{master_resume}\n\n"
        f"JOB DESCRIPTION:\n{job_description}"
    )
    return _generate_plain_text(prompt)


def generate_tailored_resume(
    job_description: str,
    master_resume: str,
    resume_bullets: list[str] | str,
) -> str:
    """Rewrite resume bullet points so they better match the job keywords.

    Enhances keyword density for ATS scanners while strictly maintaining factual
    accuracy (forbidding hallucinated positions, metrics, or technologies).

    Args:
        job_description: Full text of the employer's job posting.
        master_resume: Candidate's baseline resume for full context.
        resume_bullets: Original accomplishments list or text to optimize.

    Returns:
        Rewritten bullet points formatted with standard hyphens in plain text.
    """
    # Normalize bullet list into a line-by-line string if passed as a list
    bullets_text = (
        "\n".join(f"- {bullet}" for bullet in resume_bullets)
        if isinstance(resume_bullets, list)
        else resume_bullets
    )
    prompt = (
        "You are an expert recruiter and resume writer.\n"
        "Rewrite the provided resume bullet points to match the job description keywords.\n"
        "Keep the candidate truthful. Do not invent tools, employers, metrics, or experience.\n"
        "Make the bullets specific, action-oriented, and ATS-friendly.\n\n"
        "Output format exactly:\n"
        "Tailored Resume Bullets:\n"
        "- <rewritten bullet>\n"
        "- <rewritten bullet>\n\n"
        "Do not use markdown styling, bold text, tables, or HTML.\n"
        "Use plain text only.\n\n"
        f"MASTER RESUME:\n{master_resume}\n\n"
        f"CURRENT BULLETS:\n{bullets_text}\n\n"
        f"JOB DESCRIPTION:\n{job_description}"
    )
    return _generate_plain_text(prompt)


def _get_gemini_client() -> genai.Client:
    """Instantiate and authenticate the Google GenAI client.

    Raises:
        RuntimeError: If GEMINI_API_KEY is not configured in .env.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY in .env")
    # trust_env=False avoids unwanted system proxy interference
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(client_args={"trust_env": False}),
    )


def _generate_plain_text(prompt: str) -> str:
    """Send prompt to Gemini model with system instructions and post-process output."""
    client = _get_gemini_client()
    completion = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=(
                "You are an expert recruiter. Always return plain text only. "
                "Never return markdown, bold formatting, code fences, tables, or HTML."
            ),
            # Low temperature (0.3) ensures focused, deterministic, and factual outputs
            temperature=0.3,
        ),
    )
    return _clean_plain_text(completion.text or "")


def _clean_plain_text(text: str) -> str:
    """Sanitize LLM output by stripping any stray markdown tokens or HTML elements."""
    cleaned = text.replace("\r\n", "\n")
    # Remove markdown headers (#, ##, etc.)
    cleaned = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", cleaned)
    # Strip markdown bold and italic asterisks
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*(.*?)\*", r"\1", cleaned)
    # Strip backticks and inline code spans
    cleaned = re.sub(r"`{1,3}", "", cleaned)
    # Strip any rogue HTML tags
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    # Collapse excess consecutive blank lines
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()

