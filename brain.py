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
import time

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
    resume_bullets: list[str] | str | None = None,
) -> str:
    """Generate a complete tailored resume that mirrors the exact structure and pattern
    of the master resume while optimizing summary, skills emphasis, and experience/project
    bullet points for the target job keywords and ATS scanners.

    Args:
        job_description: Full text of the employer's job posting.
        master_resume: Candidate's baseline resume text.
        resume_bullets: Optional specific bullet points override or additional context.

    Returns:
        Complete tailored resume formatted with the exact sections and sequence
        of the master resume in clean, structured plain text.
    """
    prompt = (
        "You are an expert executive resume writer and ATS optimization specialist.\n"
        "Your task is to generate a COMPLETE tailored resume for the candidate based on their MASTER RESUME "
        "and the target JOB DESCRIPTION.\n\n"
        "CRITICAL INSTRUCTIONS:\n"
        "1. PRESERVE THE EXACT PATTERN, STRUCTURE, AND SECTIONS of the MASTER RESUME:\n"
        "   - Top Header: Exact Candidate Name and Contact Details (Email, GitHub, LinkedIn).\n"
        "   - Retain the exact same section titles in the same order:\n"
        "     * Summary\n"
        "     * Skills\n"
        "     * Experience / Internship\n"
        "     * Projects\n"
        "     * Education\n"
        "     * Certificates\n"
        "2. TAILOR CONTENT STRATEGICALLY FOR THE TARGET JOB:\n"
        "   - Summary: Align the candidate's summary directly with the target job title, company, and core tech requirements.\n"
        "   - Skills: Prioritize and highlight the candidate's skills that match the job description.\n"
        "   - Experience / Internship: Keep the exact employer, role, location, and dates. Rewrite bullet points with strong action verbs and relevant ATS keywords.\n"
        "   - Projects: Keep project titles and links. Polish descriptions and bullet points to emphasize relevant technical achievements and architectures.\n"
        "   - Education & Certificates: Keep strictly identical to the master resume.\n"
        "3. STRICT FACTUAL ACCURACY:\n"
        "   - NEVER fabricate new employers, degrees, dates, tools, or experiences not present in the master resume.\n"
        "4. CLEAN PLAIN TEXT FORMAT:\n"
        "   - Use '● ' for bullet points.\n"
        "   - Put section headings on their own lines.\n"
        "   - Do NOT use markdown asterisks (no **bold**), no backticks, no HTML, and no code fences.\n"
        "   - Do NOT include any recruiter notes, commentary, or intro/outro text. Output ONLY the resume itself.\n\n"
        f"MASTER RESUME:\n{master_resume}\n\n"
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
    
    max_retries = 3
    base_delay = 2
    
    for attempt in range(max_retries):
        try:
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
        except Exception as e:
            error_msg = str(e).lower()
            if "quota" in error_msg or "429" in error_msg or "high demand" in error_msg or "503" in error_msg or "overloaded" in error_msg:
                if attempt < max_retries - 1:
                    print(f"Gemini API busy (attempt {attempt + 1}/{max_retries}). Retrying in {base_delay} seconds...")
                    time.sleep(base_delay)
                    base_delay *= 2
                else:
                    print("Max retries reached. Trying fallback model 'gemini-1.5-flash'...")
                    try:
                        completion = client.models.generate_content(
                            model="gemini-1.5-flash",
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                system_instruction=(
                                    "You are an expert recruiter. Always return plain text only. "
                                    "Never return markdown, bold formatting, code fences, tables, or HTML."
                                ),
                                temperature=0.3,
                            ),
                        )
                        return _clean_plain_text(completion.text or "")
                    except Exception as fallback_e:
                        raise RuntimeError(f"Gemini API failed after retries. Original error: {e}. Fallback error: {fallback_e}")
            else:
                raise


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

