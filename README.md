# Autonomous Job Agent


This project is an **Autonomous Job Agent** built with Python and FastAPI. It automates the end-to-end workflow of finding relevant job postings, evaluating resume match scores with Gemini AI, generating customized PDF resumes, and tracking applications in Google Drive and Google Sheets.

---

### Pipeline Architecture & Code Status

| Component | File | Implementation Status | Purpose |
| :--- | :--- | :--- | :--- |
| **API / Orchestrator** | [main.py](file:///c:/Users/AAMIR%20SHAMSI/Agentic_Ai/jobs-automation/main.py) | **Complete** | FastAPI app with `/` (health check) and `/initiate-hunt` endpoint to coordinate scraping, AI analysis, PDF generation, and logging. |
| **Scout** | [scout.py](file:///c:/Users/AAMIR%20SHAMSI/Agentic_Ai/jobs-automation/scout.py) | **Complete** | Uses Apify's LinkedIn scraper actor (`curious_coder/linkedin-jobs-scraper`) to fetch job listings matching keywords and location. |
| **AI Brain** | [brain.py](file:///c:/Users/AAMIR%20SHAMSI/Agentic_Ai/jobs-automation/brain.py) | **Complete** | Uses Google Gemini (`gemini-2.5-flash` via `google-genai`) to score candidate-job alignment (0–100) and tailor bullet points. |
| **Output / Exporter** | [output.py](file:///c:/Users/AAMIR%20SHAMSI/Agentic_Ai/jobs-automation/output.py) | **Complete** | Generates PDF resumes using `fpdf2`, uploads them to Google Drive, and appends application rows to Google Sheets. |
| **Google Setup** | [setup_google.py](file:///c:/Users/AAMIR%20SHAMSI/Agentic_Ai/jobs-automation/setup_google.py) | **Complete** | Utility script to run initial OAuth authorization and auto-create the application tracking sheet. |
| **Candidate Resume** | [data/master_resume.txt](file:///c:/Users/AAMIR%20SHAMSI/Agentic_Ai/jobs-automation/data/master_resume.txt) | **Ready** | Base resume template is populated (~1.9 KB). |

---

### Configuration & Credential Status (`.env`)


   ```powershell
   uvicorn main:app --reload
   ```
4. **Trigger a Job Hunt**:
   Send a `POST` request to `http://127.0.0.1:8000/initiate-hunt` with parameters like keywords, location, and minimum match score.
