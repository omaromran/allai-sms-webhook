# ✅ FILE: ingestion_script.py
import json
import os

ESCALATION_RULES = {}

try:
    with open("triage_data/escalation_rules.json") as f:
        ESCALATION_RULES = json.load(f)
except Exception as e:
    print("⚠️ Failed to load escalation_rules.json:", e)


import io
import re
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
SERVICE_ACCOUNT_FILE = 'service_account.json'
TRIAGE_FOLDER_ID = os.getenv("TRIAGE_ROOT_FOLDER_ID")
OUTPUT_DIR = "triage_data"
TARGET_CATEGORIES = ["hvac", "electrical"]

# -------------------- GOOGLE SETUP --------------------
def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

# -------------------- FOLDER LISTING --------------------
def list_category_folders(service):
    query = f"'{TRIAGE_FOLDER_ID}' in parents and mimeType = 'application/vnd.google-apps.folder'"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    folders = results.get('files', [])
    print("📁 Found subfolders:", [f"{f['name']} ({f['id']})" for f in folders])
    return folders

# -------------------- FILE UTILITIES --------------------
def export_google_doc_as_text(service, file_id):
    request = service.files().export_media(fileId=file_id, mimeType='text/plain')
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.seek(0)
    return fh.read().decode('utf-8')

# -------------------- TRIAGE PARSING --------------------
def parse_triage_text(text):
    result = {"clusters": [], "media_prompts": {}}
    current = {}
    section = None

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        lower = line.lower()

        if lower.startswith("category"):
            result["category"] = line.split(":")[-1].strip().lower()

        elif lower.startswith("cluster"):
            if current:
                result["clusters"].append(current)
            current = {"name": line.split(":")[-1].strip(), "examples": [], "triage_questions": [], "escalation_rules": {}}

        elif lower.startswith("examples"):
            section = "examples"
        elif lower.startswith("triage notes"):
            section = "triage_questions"
        elif lower.startswith("escalation"):
            section = "escalation"
        elif lower.startswith("media prompts"):
            section = "media"
        elif section == "examples":
            current["examples"].append(line.strip("- "))
        elif section == "triage_questions":
            current["triage_questions"].append(line.strip("- "))
        elif section == "escalation":
            rule_type = "next_day"
            if "emergency" in line.lower():
                rule_type = "emergency"
            elif "same-day" in line.lower() or "same day" in line.lower():
                rule_type = "same_day"
            current["escalation_rules"].setdefault(rule_type, []).append(line.strip("- "))
        elif section == "media":
            if "photo" in line.lower():
                result["media_prompts"]["photo"] = line
            elif "video" in line.lower():
                result["media_prompts"]["video"] = line
            elif "audio" in line.lower():
                result["media_prompts"]["audio"] = line

    if current:
        result["clusters"].append(current)
    return result

# -------------------- DOWNLOAD & SAVE TRIAGE --------------------
def download_and_parse_triage_file(service, folder_id, category):
    query = f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.document' and name contains 'Triage'"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])
    if not files:
        print(f"⚠️ No Triage Flow file found for {category}")
        return

    print(f"📄 Found triage file: {files[0]['name']}")
    text = export_google_doc_as_text(service, files[0]['id'])
    parsed = parse_triage_text(text)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(f"{OUTPUT_DIR}/{category}.json", "w") as f:
        json.dump(parsed, f, indent=2)
    print(f"✅ Saved {category}.json")

# -------------------- MAIN --------------------
if __name__ == "__main__":
    print("🔍 Loaded folder ID:", TRIAGE_FOLDER_ID)
    service = get_drive_service()
    folders = list_category_folders(service)

    for folder in folders:
        name = folder['name'].lower()
        if name in TARGET_CATEGORIES:
            download_and_parse_triage_file(service, folder['id'], name)

    print("✅ Ingestion complete.")


    # triage_engine.py

def classify_issue(message):
    # Your implementation
    return {
        "category": "hvac",
        "cluster": "example",
        "urgency": "normal",
        "followup_questions": ["example?"],
        "should_escalate": False
    }

def should_bypass_landlord(triage_info, media_present=False):
    global ESCALATION_RULES
    message = triage_info.get("message", "").lower()
    urgency = triage_info.get("urgency", "normal")

    if not message:
        print("⚠️ Warning: 'message' key missing from triage_info.")

    print("\n🔍 Escalation Debug Info:")
    print(f"Message: {message}")
    print(f"Urgency: {urgency}")
    print(f"Media Present: {media_present}")

    # 1. Emergency keyword match
    for keyword in ESCALATION_RULES.get("emergency_keywords", []):
        if keyword.lower() in message:
            print(f"⚠️ Emergency keyword triggered: '{keyword}'")
            return True

    # 2. Urgency phrases
    for phrase in ESCALATION_RULES.get("urgency_phrases", []):
        if phrase.lower() in message:
            print(f"⚠️ Urgency phrase triggered: '{phrase}'")
            return True

    # 3. Time-based escalation
    now = datetime.now()
    if now.hour < 7 or now.hour >= 21 or now.weekday() >= 5:
        print("⏰ Escalation due to after-hours or weekend")
        return True

    # 4. High urgency + no media
    if urgency == "high" and not media_present:
        print("📸 Urgent issue reported without media — escalating for review")
        return True

    print("✅ No escalation triggered.")
    return False