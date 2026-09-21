"""Apify scraper integration for job discovery.

This module interfaces with the Apify platform to run an automated LinkedIn
jobs scraper actor. It accepts user-defined search keywords and locations,
dispatches the scrape task, and standardizes the returned raw data.
"""

from __future__ import annotations

import os
import re
from typing import Any

from apify_client import ApifyClient
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Apify Actor and scraping configuration defaults
# curious_coder/linkedin-jobs-scraper extracts public LinkedIn job postings without login
APIFY_ACTOR_ID = os.getenv("APIFY_ACTOR_ID", "curious_coder/linkedin-jobs-scraper")
DEFAULT_JOB_COUNT = int(os.getenv("APIFY_JOB_COUNT", "10"))
DEFAULT_DATE_POSTED = os.getenv("APIFY_DATE_POSTED", "past-month")
DEFAULT_EXPERIENCE_LEVEL = ["internship", "entry_level"]
DEFAULT_WORK_TYPE = ["on_site", "remote", "hybrid"]


def get_jobs(keywords: str, location: str, max_jobs: int = DEFAULT_JOB_COUNT) -> list[dict[str, str]]:
    """Scrape LinkedIn jobs via Apify and return normalized records.

    Args:
        keywords: Search query terms (e.g. 'Full Stack Developer', 'Python Engineer').
        location: Geographic target (e.g. 'Karachi', 'Remote', 'United States').

    Returns:
        A list of cleaned job dictionaries containing title, company,
        descriptionText, and jobUrl.

    Raises:
        RuntimeError: If APIFY_API_TOKEN is not configured in .env.
    """
    # Verify API token presence before initiating client connection
    token = os.getenv("APIFY_API_TOKEN")
    if not token:
        raise RuntimeError("Missing APIFY_API_TOKEN in .env")

    # Initialize Apify client with authenticated token
    client = ApifyClient(token)

    # Prepare actor parameters matching misceres/indeed-scraper specifications
    run_input = {
        "position": keywords,
        "location": location,
        "country": "US", # Defaulting to US, can be customized
        "maxItems": max_jobs,
        "maxItemsPerSearch": max_jobs,
    }

    # Execute the scraping actor synchronously and await completion
    run = client.actor(APIFY_ACTOR_ID).call(run_input=run_input)

    # Retrieve default dataset ID where scrape results are stored
    dataset_id = getattr(run, "defaultDatasetId", None) or getattr(run, "default_dataset_id", None)
    if not dataset_id and hasattr(run, "get"):
        dataset_id = run.get("defaultDatasetId")
    if not dataset_id:
        return []

    # Iterate through raw dataset items and sanitize each job entry
    return [_clean_job(item) for item in client.dataset(dataset_id).iterate_items()]


def _clean_job(item: dict[str, Any]) -> dict[str, str]:
    """Normalize and extract required fields from a raw Apify dataset item."""
    return {
        # Normalize job title
        "title": _clean_text(item.get("title") or item.get("positionName") or item.get("jobTitle")),
        # Normalize company name (handling alternate key formats)
        "company": _clean_text(item.get("companyName") or item.get("company")),
        # Normalize job description text for LLM analysis
        "descriptionText": _clean_text(item.get("descriptionText") or item.get("description")),
        # Normalize direct application / posting URL
        "jobUrl": _clean_text(item.get("jobUrl") or item.get("link") or item.get("url")),
    }


def _clean_text(value: Any) -> str:
    """Strip redundant whitespace, linebreaks, and handle None values safely."""
    if value is None:
        return ""
    # Collapse multiple spaces, tabs, and newlines into a single clean space
    return re.sub(r"\s+", " ", str(value)).strip()

