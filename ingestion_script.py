import socket

# 🔧 Force all DNS resolutions to use IPv4 (to prevent httplib2 timeouts)
orig_getaddrinfo = socket.getaddrinfo
def force_ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = force_ipv4_getaddrinfo

# ingestion_script.py
import json, os, io, difflib
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

def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

import socket
socket.setdefaulttimeout(30)  # set timeout to 10 seconds

def list_category_folders(service):
    query = f"'{TRIAGE_FOLDER_ID}' in parents and mimeType = 'application/vnd.google-apps.folder'"
    print("📡 Running Drive query:", query)
    try:
        results = service.files().list(q=query, fields="files(id, name)").execute()
        folders = results.get('files', [])
        print("📁 Found subfolders:", [f"{f['name']} ({f['id']})" for f in folders])
        return folders
    except Exception as e:
        print("❌ Error during Drive query:", e)
        return []

def export_google_doc_as_text(service, file_id):
    request = service.files().export_media(fileId=file_id, mimeType='text/plain')
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.seek(0)
    return fh.read().decode('utf-8')

def parse_triage_text(text):
    result = {"clusters": [], "media_prompts": {}}
    current = {}
    section = None

    for line in text.splitlines():
        line = line.strip()
        if not line: continue
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
            if "emergency" in lower:
                rule_type = "emergency"
            elif "same-day" in lower or "same day" in lower:
                rule_type = "same_day"
            current["escalation_rules"].setdefault(rule_type, []).append(line.strip("- "))
        elif section == "media":
            if "photo" in lower:
                result["media_prompts"]["photo"] = line
            elif "video" in lower:
                result["media_prompts"]["video"] = line
            elif "audio" in lower:
                result["media_prompts"]["audio"] = line

    if current:
        result["clusters"].append(current)
    return result

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

if __name__ == "__main__":
    print("🔍 Loaded folder ID:", TRIAGE_FOLDER_ID)
    service = get_drive_service()
    folders = list_category_folders(service)

    for folder in folders:
        name = folder['name'].lower()
        if name in TARGET_CATEGORIES:
            download_and_parse_triage_file(service, folder['id'], name)

    print("✅ Ingestion complete.")