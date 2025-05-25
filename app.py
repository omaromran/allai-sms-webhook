from flask import Flask, request
from flask_cors import CORS
from openai import OpenAI
import os
import requests
import json
from triage_engine import classify_issue, should_bypass_landlord
from datetime import datetime
import smtplib
from email.mime.text import MIMEText

app = Flask(__name__)
CORS(app)

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

VONAGE_API_KEY = os.environ["VONAGE_API_KEY"]
VONAGE_API_SECRET = os.environ["VONAGE_API_SECRET"]
AIRTABLE_TOKEN = os.environ["AIRTABLE_TOKEN"]
AIRTABLE_BASE_ID = os.environ["AIRTABLE_BASE_ID"]
AIRTABLE_TABLE_NAME = "Issues"
VISUAL_CATEGORIES = {"plumbing", "pest", "appliance", "other"}

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_PASS = os.environ["GMAIL_APP_PASS"]
L1_EMAIL = os.environ.get("L1_EMAIL", "omranomar1@gmail.com")


def generate_issue_id():
    from random import randint
    return f"ISSUE-{randint(100000, 999999)}"

def is_new_issue(message):
    message = message.lower()
    return any(phrase in message for phrase in ["new issue", "another issue", "different problem", "new problem"])

def is_resolved(message):
    message = message.lower()
    return any(phrase in message for phrase in ["fixed", "resolved", "no longer", "no issue", "solved", "it’s all good"])

def get_unit_for_phone(phone):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/Tenants"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json"
    }
    params = {
        "filterByFormula": f"{{Phone}}='{phone}'"
    }
    response = requests.get(url, headers=headers, params=params)
    records = response.json().get("records", [])

    if records:
        return records[0]["fields"].get("Unit", "Unknown")
    else:
        return "Unknown"

def notify_l1_via_gmail(issue_id, summary, category, urgency, record_id, unit):
    airtable_link = f"https://airtable.com/{AIRTABLE_BASE_ID}/{record_id}"
    body = f"""
    🚨 Escalated Maintenance Issue: {issue_id}

    Unit: {unit}
    Summary: {summary}
    Category: {category}
    Urgency: {urgency}

    View in Airtable: {airtable_link}
    """

    msg = MIMEText(body)
    msg["Subject"] = f"🚨 Escalated Issue: {issue_id}"
    msg["From"] = GMAIL_USER
    msg["To"] = L1_EMAIL

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASS)
        server.send_message(msg)

    print("📧 L1 email alert sent via Gmail")

def get_or_create_issue(phone, message, triage):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json"
    }
    params = {
        "filterByFormula": f"AND({{Phone}}='{phone}', OR({{Status}}='Open', {{Status}}='Escalated'))"
    }
    response = requests.get(url, headers=headers, params=params)
    records = response.json().get("records", [])

    if records and not is_new_issue(message):
        issue_id = records[0]["fields"].get("Issue ID", "Unknown")
        record_id = records[0]["id"]
        print(f"📌 Found existing issue ID: {issue_id}")
        return issue_id, record_id, False

    issue_id = generate_issue_id()
    fields = {
        "Issue ID": issue_id,
        "Phone": phone,
        "Message Summary": message[:50],
        "Message": message,
        "Category": triage["category"],
        "Urgency": triage["urgency"],
        "Escalated": triage["should_escalate"],
        "Follow-ups": "\n".join(triage["followup_questions"]),
        "Status": "Open"
    }
    create_response = requests.post(url, headers=headers, json={"fields": fields})
    print("🆕 Created new issue with ID:", issue_id)
    return issue_id, create_response.json().get("id"), True

def log_issue_to_airtable(record_id, new_message, mark_resolved=False):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}/{record_id}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json"
    }

    get_resp = requests.get(url, headers=headers)
    current_message = get_resp.json().get("fields", {}).get("Message", "")
    full_message = (current_message + "\n" + new_message).strip()

    updates = { "Message": full_message }
    if mark_resolved:
        updates["Status"] = "Resolved"

    try:
        response = requests.patch(url, headers=headers, json={"fields": updates})
        print("Airtable update status:", response.status_code, response.text)
    except Exception as e:
        print("❌ Airtable update failed:", str(e))

@app.route("/messages", methods=["POST"])
def vonage_whatsapp():
    data = request.get_json()
    print("Incoming WhatsApp:", data)

    try:
        msg = data.get("text")
        user_number = data.get("from")
        print("Message from WhatsApp user:", msg)

        triage = classify_issue(msg)
        issue_id, record_id, is_new = get_or_create_issue(user_number, msg, triage)

        # Retrieve Airtable record to check media flag
        record_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}/{record_id}"
        headers = {
            "Authorization": f"Bearer {AIRTABLE_TOKEN}",
            "Content-Type": "application/json"
        }
        media_submitted = False
        try:
            r = requests.get(record_url, headers=headers)
            fields = r.json().get("fields", {})
            media_submitted = fields.get("Media Submitted", False)
        except:
            pass

        should_escalate = should_bypass_landlord(triage, media_present=media_submitted)
        resolved = is_resolved(msg)

        if should_escalate:
            unit = get_unit_for_phone(user_number)
            notify_l1_via_gmail(issue_id, msg[:50], triage["category"], triage["urgency"], record_id, unit)

        if resolved:
            log_issue_to_airtable(record_id, msg, mark_resolved=True)
            reply = f"Thanks for letting me know! I’ve marked issue {issue_id} as resolved. Let me know if you need anything else."
        else:
            escalation_instruction = (
                f"This issue has been assigned to {issue_id}. It is urgent and requires escalation to a human. Please stay tuned while we coordinate."
                if should_escalate else
                f"This issue has been assigned to {issue_id}. It's not urgent, but I’ll ask a few more questions to better understand."
            )

            triage_prompt = (
                f"You are Allai, a professional assistant trained in property maintenance triage.\n"
                f"The issue appears to relate to: {triage['category']}.\n"
                f"{escalation_instruction}\n"
                f"Ask the following:\n"
                f"- " + "\n- ".join(triage['followup_questions'])
            )

            gpt_reply = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": triage_prompt},
                    {"role": "user", "content": msg}
                ]
            ).choices[0].message.content

            reply = gpt_reply
            if triage["category"] in VISUAL_CATEGORIES and not media_submitted:
                reply += f"\n\n📸 If possible, upload a photo or video of the issue here:\nhttps://allai-upload.web.app?issue_id={issue_id}"

            log_issue_to_airtable(record_id, msg)

        channel = data.get("channel")
        if channel == "messenger":
            payload = {
                "from": {"type": "messenger", "id": "699775536544257"},
                "to": {"type": "messenger", "id": data["from"]},
                "message": {"content": {"type": "text", "text": reply}}
            }
        elif channel == "whatsapp":
            payload = {
                "from": {"type": "whatsapp", "number": "15557817931"},
                "to": {"type": "whatsapp", "number": data["from"]},
                "message": {"content": {"type": "text", "text": reply}}
            }

        response = requests.post(
            "https://api.nexmo.com/v0.1/messages",
            json=payload,
            auth=(VONAGE_API_KEY, VONAGE_API_SECRET)
        )
        print("Vonage send status:", response.status_code, response.text)
        return "ok"

    except Exception as e:
        print("Error:", e)
        return "error", 500

@app.route("/media-upload", methods=["POST", "OPTIONS"])
def media_upload():
    if request.method == "OPTIONS":
        return '', 200

    data = request.get_json()
    issue_id = data.get("issue_id")
    media_urls = data.get("media_urls", [])

    if not issue_id or not media_urls:
        return {"error": "Missing issue_id or media_urls"}, 400

    search_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json"
    }
    params = {
        "filterByFormula": f"{{Issue ID}}='{issue_id}'"
    }
    response = requests.get(search_url, headers=headers, params=params)
    records = response.json().get("records", [])

    if not records:
        return {"error": "Issue ID not found"}, 404

    record_id = records[0]["id"]
    patch_url = f"{search_url}/{record_id}"
    attachments = [{"url": url} for url in media_urls]
    payload = {
        "fields": {
            "Media": attachments,
            "Media Submitted": True
        }
    }

    update_resp = requests.patch(patch_url, headers=headers, json=payload)
    print("Media upload Airtable status:", update_resp.status_code, update_resp.text)
    return {"status": "success"}, 200
