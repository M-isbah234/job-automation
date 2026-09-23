# Autonomous Job Application Agent

## Overview
This project provides an automated pipeline for job searching, candidate evaluation, and resume generation. Built on FastAPI, the agent scrapes job listings, evaluates the candidate's alignment with the role using Google Gemini, generates a tailored PDF resume for highly matched positions, and logs the results directly into a Google Sheets tracker with links to the generated documents in Google Drive.

## Pipeline Architecture
1. **Scout (Job Scraping):** Interfaces with the Apify platform to scrape job postings from Indeed based on user-defined keywords, location, and limits.
2. **Brain (AI Analysis):** Utilizes the Google Gemini API to analyze the candidate's base resume against the scraped job descriptions. It produces a match score (0-100) and rewrites resume bullet points to optimize for Applicant Tracking Systems (ATS).
3. **Output (Document Generation & Tracking):** Generates a formatted PDF resume using the tailored content, uploads the document to Google Drive, and appends a tracking row (Company, Position, Score, Links) to a designated Google Sheet.
4. **User Interface:** Provides a responsive, web-based frontend dashboard served via FastAPI to configure parameters (keywords, location, match threshold, max jobs) and monitor the automation in real-time.

## Prerequisites
* Python 3.10 or higher
* Apify Account (for the Indeed scraper API token)
* Google AI Studio Account (for the Gemini API key)
* Google Cloud Console Account (for Google Drive and Sheets OAuth credentials)

## Installation & Setup

1. **Install dependencies:**
Ensure you are in the project root directory, then run:
```bash
pip install -r requirements.txt
```

2. **Configure Environment Variables:**
Ensure your `.env` file is populated with your respective API keys:
* `APIFY_API_TOKEN`: Your Apify API token.
* `GEMINI_API_KEY`: Your Google Gemini API key.
* `MASTER_RESUME_FILE`: Path to your base resume text file (default is `data/master_resume.txt`).

3. **Configure Google Workspace Credentials:**
* Generate an OAuth 2.0 Client ID (Desktop App) from the Google Cloud Console.
* Download the credentials JSON file.
* Rename the file to `client_secret.json` and place it in the `credentials/` directory.

4. **Initialize Google Authentication:**
Run the setup script to authenticate via your browser and initialize the tracking spreadsheet:
```bash
python setup_google.py
```
This process will automatically generate a new Google Sheet and update your `.env` file with the `GOOGLE_SHEET_ID`.

## Usage

1. **Start the Application Server:**
Run the following command in your terminal to start the FastAPI server:
```bash
uvicorn main:app --reload
```

2. **Access the Dashboard:**


3. **Initiate a Job Hunt:**
Use the provided interface to enter your target job title, location, minimum match score, and maximum jobs to scrape. The application will process the jobs sequentially, print progress to the terminal, and display the final results on the dashboard upon completion.
