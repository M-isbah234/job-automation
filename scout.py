"""Apify scraper integration for job discovery."""

from __future__ import annotations

import os
import re
from typing import Any

from apify_client import ApifyClient
from dotenv import load_dotenv


load_dotenv()

APIFY_ACTOR_ID = os.getenv("APIFY_ACTOR_ID", "curious_coder/linkedin-jobs-scraper")
DEFAULT_JOB_COUNT = int(os.getenv("APIFY_JOB_COUNT", "10"))
DEFAULT_DATE_POSTED = os.getenv("APIFY_DATE_POSTED", "past-month")
DEFAULT_EXPERIENCE_LEVEL = ["internship", "entry_level"]
DEFAULT_WORK_TYPE = ["on_site", "remote", "hybrid"]


def get_jobs(keywords: str, location: str) -> list[dict[str, str]]:
    """Scrape LinkedIn jobs and return only the fields needed by the AI brain."""
    token = os.getenv("APIFY_API_TOKEN")
    if not token:
        raise RuntimeError("Missing APIFY_API_TOKEN in .env")

    client = ApifyClient(token)
    run_input = {
        "includeKeyword": keywords,
        "locationName": location,
        "datePosted": DEFAULT_DATE_POSTED,
        "experienceLevel": DEFAULT_EXPERIENCE_LEVEL,
        "workType": DEFAULT_WORK_TYPE,
        "count": DEFAULT_JOB_COUNT,
    }

    run = client.actor(APIFY_ACTOR_ID).call(run_input=run_input)
    dataset_id = run.get("defaultDatasetId")
    if not dataset_id:
        return []

    return [_clean_job(item) for item in client.dataset(dataset_id).iterate_items()]


def _clean_job(item: dict[str, Any]) -> dict[str, str]:
    return {
        "title": _clean_text(item.get("title")),
        "company": _clean_text(item.get("companyName") or item.get("company")),
        "descriptionText": _clean_text(item.get("descriptionText")),
        "jobUrl": _clean_text(item.get("jobUrl") or item.get("link")),
    }


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()
