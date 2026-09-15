"""Gemini AI logic for resume matching and tailoring."""

from __future__ import annotations

import os
import re

from dotenv import load_dotenv
from google import genai
from google.genai import types


load_dotenv()

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def analyze_job(job_description: str, master_resume: str) -> str:
    """Compare a resume with a job description and return plain-text analysis."""
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
    """Rewrite resume bullet points so they better match the job keywords."""
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
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY in .env")
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(client_args={"trust_env": False}),
    )


def _generate_plain_text(prompt: str) -> str:
    client = _get_gemini_client()
    completion = client.models.generate_content(
        model=GEMINI_MODEL,
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


def _clean_plain_text(text: str) -> str:
    cleaned = text.replace("\r\n", "\n")
    cleaned = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", cleaned)
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*(.*?)\*", r"\1", cleaned)
    cleaned = re.sub(r"`{1,3}", "", cleaned)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
