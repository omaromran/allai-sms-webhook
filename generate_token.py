from google.oauth2 import service_account
import google.auth.transport.requests

creds = service_account.Credentials.from_service_account_file("service_account.json", scopes=["https://www.googleapis.com/auth/drive.readonly"])
auth_req = google.auth.transport.requests.Request()
creds.refresh(auth_req)
print(creds.token)