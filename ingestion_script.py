# ingestion_script.py
import os
import json
from docx import Document
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
from datetime import datetime

# Constants
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
SERVICE_ACCOUNT_FILE = 'service_account.json'  # Store this securely
TRIAGE_FOLDER_ID = os.getenv("14Jd7EVIvuLZRhXSqHxzgQ2B3cBaQgn3z")  # ID of Allai-Knowledge-Hub in Drive
OUTPUT_DIR = "triage_data"

# Setup Google Drive service
def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

# Get subfolders of the main triage folder (e.g., hvac/, electrical/)
def list_category_folders(service):
    query = f"'{TRIAGE_FOLDER_ID}' in parents and mimeType = 'application/vnd.google-apps.folder'"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    return results.get('files', [])

# Download Triage Flow.docx and parse content
def download_and_parse(service, folder_id, category):
    query = f"'{folder_id}' in parents and name contains 'Triage Flow' and mimeType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])
    if not files:
        print(f"No Triage Flow found for {category}")
        return

    file_id = files[0]['id']
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    fh.seek(0)

    with open(f"/tmp/{category}_triage.docx", "wb") as f:
        f.write(fh.read())

    doc = Document(f"/tmp/{category}_triage.docx")
    parsed = parse_triage_doc(doc)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(f"{OUTPUT_DIR}/{category}.json", "w") as f:
        json.dump(parsed, f, indent=2)

# Extract structured content
def parse_triage_doc(doc):
    result = {"clusters": [], "media_prompts": {}}
    current = {}
    section = None

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        if text.lower().startswith("category"):
            result["category"] = text.split(":")[-1].strip().lower()
        elif text.startswith("## Cluster"):
            if current:
                result["clusters"].append(current)
            current = {"name": text.replace("## Cluster:", "").strip(), "examples": [], "triage_questions": [], "escalation_rules": {}}
        elif text.startswith("### Examples"):
            section = "examples"
        elif text.startswith("### Triage Notes"):
            section = "triage_questions"
        elif text.startswith("### Escalation"):
            section = "escalation"
        elif text.startswith("## Media Prompts"):
            section = "media"
        elif section == "examples":
            current["examples"].append(text.strip("- "))
        elif section == "triage_questions":
            current["triage_questions"].append(text.strip("- "))
        elif section == "escalation":
            if "emergency" in text.lower():
                current["escalation_rules"].setdefault("emergency", []).append(text.strip("- "))
            elif "same-day" in text.lower():
                current["escalation_rules"].setdefault("same_day", []).append(text.strip("- "))
            elif "next-day" in text.lower() or "within" in text.lower():
                current["escalation_rules"].setdefault("next_day", []).append(text.strip("- "))
        elif section == "media":
            if "photo" in text.lower():
                result["media_prompts"]["photo"] = text
            elif "video" in text.lower():
                result["media_prompts"]["video"] = text
            elif "audio" in text.lower():
                result["media_prompts"]["audio"] = text

    if current:
        result["clusters"].append(current)

    return result

# Main trigger for cron
if __name__ == "__main__":
    drive_service = get_drive_service()
    folders = list_category_folders(drive_service)
    for folder in folders:
        download_and_parse(drive_service, folder['id'], folder['name'].lower())
    print("✅ Ingestion complete.")
