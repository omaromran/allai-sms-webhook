import os
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
SERVICE_ACCOUNT_FILE = 'service_account.json'
FOLDER_ID = os.getenv("TRIAGE_ROOT_FOLDER_ID")

def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

if __name__ == "__main__":
    print("📡 Testing Google Drive API access...")

    try:
        service = get_drive_service()
        query = f"'{FOLDER_ID}' in parents and mimeType = 'application/vnd.google-apps.folder'"
        results = service.files().list(q=query, fields="files(id, name)").execute()
        folders = results.get("files", [])
        for f in folders:
            print(f"📁 {f['name']} ({f['id']})")
    except Exception as e:
        print("❌ Test failed:", e)