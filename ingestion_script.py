# ✅ FILE: ingestion_script.py
import os
import json
import io
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from docx import Document  # For fallback Word parsing

load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
SERVICE_ACCOUNT_FILE = 'service_account.json'
TRIAGE_FOLDER_ID = os.getenv("TRIAGE_ROOT_FOLDER_ID")
OUTPUT_DIR = "triage_data"
TARGET_CATEGORIES = ["hvac", "electrical"]

def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def list_category_folders(service):
    query = f"'{TRIAGE_FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.folder'"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    folders = results.get('files', [])
    print("📁 Found subfolders:", [f"{f['name']} ({f['id']})" for f in folders])
    return folders

def export_google_doc_text(service, file_id):
    try:
        request = service.files().export_media(fileId=file_id, mimeType='text/plain')
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.seek(0)
        return fh.read().decode('utf-8')
    except Exception as e:
        print(f"⚠️ Failed to export Google Doc as text: {e}")
        return None

def download_docx_file(service, file_id, name):
    print("📥 Downloading Word (.docx) file...")
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    fh.seek(0)  # ✅ Reset buffer pointer before saving

    # Sanitize filename
    safe_name = name.lower().replace(" ", "_").replace("/", "_")
    path = f"/tmp/{safe_name}.docx"

    with open(path, "wb") as f:
        f.write(fh.read())  # ✅ This now works correctly

    print(f"📁 Saved to: {path}")
    return path

def parse_text_to_json(text):
    result = {"clusters": [], "media_prompts": {}}
    current = {}
    section = None

    for line in text.splitlines():
        line = line.strip()
        if not line: continue

        if line.lower().startswith("category"):
            result["category"] = line.split(":")[-1].strip().lower()
        elif line.lower().startswith("## cluster"):
            if current: result["clusters"].append(current)
            current = {"name": line.split(":")[-1].strip(), "examples": [], "triage_questions": [], "escalation_rules": {}}
        elif line.lower().startswith("### examples"):
            section = "examples"
        elif line.lower().startswith("### triage notes"):
            section = "triage_questions"
        elif line.lower().startswith("### escalation"):
            section = "escalation"
        elif line.lower().startswith("## media prompts"):
            section = "media"
        elif section == "examples":
            current["examples"].append(line.strip("- "))
        elif section == "triage_questions":
            current["triage_questions"].append(line.strip("- "))
        elif section == "escalation":
            rule = "next_day"
            if "emergency" in line.lower():
                rule = "emergency"
            elif "same-day" in line.lower():
                rule = "same_day"
            current["escalation_rules"].setdefault(rule, []).append(line.strip("- "))
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

def parse_docx_to_text(path):
    doc = Document(path)
    return "\n".join([para.text for para in doc.paragraphs])

def download_and_parse_triage_file(service, folder_id, category):
    query = f"'{folder_id}' in parents and name contains 'Triage Flow'"
    files = service.files().list(q=query, fields="files(id, name, mimeType)").execute().get('files', [])
    if not files:
        print(f"❌ No triage file found for {category}")
        return

    file = files[0]
    print(f"📄 Found triage file: {file['name']} ({file['mimeType']})")

    text = None
    if file['mimeType'] == 'application/vnd.google-apps.document':
        text = export_google_doc_text(service, file['id'])
    elif file['mimeType'] == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document':
        print("📥 Downloading Word (.docx) file...")
        docx_path = download_docx_file(service, file['id'], category)
        if docx_path:
            text = parse_docx_to_text(docx_path)
        else:
            print(f"❌ Failed to download {file['name']} as .docx")
            return
    else:
        print(f"⚠️ Skipping file (unsupported type): {file['mimeType']}")
        return

    if not text:
        print(f"⚠️ Failed to extract text from {file['name']}")
        return

    parsed = parse_text_to_json(text)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(f"{OUTPUT_DIR}/{category}.json", "w") as f:
        json.dump(parsed, f, indent=2)
    print(f"✅ Saved {category}.json")

# Main
if __name__ == "__main__":
    print("🔍 Loaded folder ID:", TRIAGE_FOLDER_ID)
    service = get_drive_service()
    folders = list_category_folders(service)

    for folder in folders:
        name = folder['name'].lower()
        if name in TARGET_CATEGORIES:
            download_and_parse_triage_file(service, folder['id'], name)

    print("✅ Ingestion complete.")