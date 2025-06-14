from flask import Flask, request
from flask_cors import CORS
from openai import OpenAI
import os
import requests
import json
import time
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
VISUAL_CATEGORIES = {"plumbing", "pest", "appliance", "other", "hvac"}

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_PASS = os.environ["GMAIL_APP_PASS"]
L1_EMAIL = os.environ.get("L1_EMAIL", "omranomar1@gmail.com")


def generate_issue_id():
    from random import randint
    return f"ISSUE-{randint(100000, 999999)}"


def is_new_issue(message):
    message = message.lower()
    return any(phrase in message for phrase in [
        "new issue", "another issue", "different problem", "new problem"
    ])


def is_resolved(message):
    message = message.lower()
    return any(phrase in message for phrase in [
        "fixed", "resolved", "no longer", "no issue", "solved", "it’s all good"
    ])


def get_unit_for_phone(phone):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/Tenants"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json"
    }
    params = {"filterByFormula": f"{{Phone}}='{phone}'"}
    resp = requests.get(url, headers=headers, params=params).json()
    records = resp.get("records", [])
    return records[0]["fields"].get("Unit", "Unknown") if records else "Unknown"


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


def get_or_create_issue(phone, message, triage=None):
    """
    triage only needed for new issues.
    returns: (issue_id, record_id, is_new)
    """
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json"
    }
    params = {
        "filterByFormula":
        f"AND({{Phone}}='{phone}', OR({{Status}}='Open', {{Status}}='Escalated'))"
    }
    resp = requests.get(url, headers=headers, params=params).json()
    records = resp.get("records", [])

    if records and not is_new_issue(message):
        rec = records[0]
        issue_id = rec["fields"].get("Issue ID", "Unknown")
        print(f"📌 Found existing issue ID: {issue_id}")
        return issue_id, rec["id"], False

    # new issue
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
    create_resp = requests.post(url, headers=headers, json={"fields": fields}).json()
    print("🆕 Created new issue with ID:", issue_id)
    return issue_id, create_resp.get("id"), True


def log_issue_to_airtable(record_id, new_message, mark_resolved=False):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}/{record_id}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json"
    }
    get_resp = requests.get(url, headers=headers).json()
    current = get_resp.get("fields", {}).get("Message", "")
    full = (current + "\n" + new_message).strip()

    updates = {"Message": full}
    if mark_resolved:
        updates["Status"] = "Resolved"

    resp = requests.patch(url, headers=headers, json={"fields": updates})
    print("Airtable update status:", resp.status_code, resp.text)


@app.route("/messages", methods=["POST"])
def vonage_whatsapp():
    data = request.get_json()
    print("Incoming WhatsApp:", data)

    msg = data.get("text", "")
    user_number = data.get("from")
    print("Message from user:", msg)

    # classification & triage
    triage = classify_issue(msg)
    issue_id, record_id, is_new = get_or_create_issue(user_number, msg, triage=triage)

    # check if media already submitted
    record_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}/{record_id}"
    media_submitted = False
    try:
        fields = requests.get(record_url,
                              headers={
                                  "Authorization": f"Bearer {AIRTABLE_TOKEN}",
                                  "Content-Type": "application/json"
                              }).json().get("fields", {})
        media_submitted = fields.get("Media Submitted", False)
    except:
        pass

    # escalation logic
    should_escalate = should_bypass_landlord(triage, media_present=media_submitted)
    resolved = is_resolved(msg)

    if should_escalate:
        unit = get_unit_for_phone(user_number)
        notify_l1_via_gmail(issue_id, msg[:50], triage["category"],
                            triage["urgency"], record_id, unit)

    if resolved:
        log_issue_to_airtable(record_id, msg, mark_resolved=True)
        reply = f"Thanks! I’ve marked issue {issue_id} as resolved."
    else:
        # build follow-up prompt
        escalation_txt = (
            "🚨 This has been escalated and flagged as urgent."
            if should_escalate else
            f"I understand you’re reporting a {triage['category']} issue."
        )
        prompt = (
            f"You are Allai, a property-maintenance assistant.\n"
            f"Category: {triage['category']}\n"
            f"Urgency: {triage['urgency']}\n"
            f"{escalation_txt}\n"
            f"Ask:\n- " + "\n- ".join(triage["followup_questions"])
        )

        gpt_resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": msg}
            ]
        ).choices[0].message.content

        reply = gpt_resp
        if triage["category"] in VISUAL_CATEGORIES and not media_submitted:
            reply += (
                f"\n\n📸 Please upload a photo of the issue here:\n"
                f"https://allai-upload.web.app?issue_id={issue_id}\n"
                "Then return to this chat."
            )

        log_issue_to_airtable(record_id, msg)

    # send out via Vonage
    out = {
        "from": {"type": data["channel"], "id": "699775536544257"},
        "to": {"type": data["channel"], "id": user_number},
        "message": {"content": {"type": "text", "text": reply}}
    }
    resp = requests.post("https://api.nexmo.com/v0.1/messages",
                         json=out,
                         auth=(VONAGE_API_KEY, VONAGE_API_SECRET))
    print("Vonage send status:", resp.status_code, resp.text)
    return "ok"


@app.route("/media-upload", methods=["POST", "OPTIONS"])
def media_upload():
    # CORS preflight
    if request.method == "OPTIONS":
        return "", 200

    data = request.get_json()
    issue_id = data.get("issue_id")
    media_urls = data.get("media_urls", [])
    if not issue_id or not media_urls:
        return {"error": "Missing issue_id or media_urls"}, 400

    # find record
    base = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json"
    }
    recs = requests.get(base,
                        headers=headers,
                        params={"filterByFormula": f"{{Issue ID}}='{issue_id}'"}
                       ).json().get("records", [])
    if not recs:
        return {"error": "Issue ID not found"}, 404
    record_id = recs[0]["id"]

    # attach media
    attachments = [{"url": url} for url in media_urls]
    payload = {"fields": {"Media": attachments, "Media Submitted": True}}
    update = requests.patch(f"{base}/{record_id}",
                            headers=headers,
                            json=payload)
    print("Media upload Airtable status:", update.status_code, update.text)

    # slight delay to ensure Airtable write
    time.sleep(1)

    # run vision & store diagnosis
    vision_resp = client.chat.completions.create(
        model="gpt-4-vision-preview",
        messages=[
            {"role": "system",
             "content": "You are an expert at diagnosing HVAC and home-maintenance images."},
            {"role": "user",
             "content": f"Analyze this image and suggest what’s wrong and how to fix it:\n{media_urls[0]}"}
        ]
    ).choices[0].message.content

    # write back to Airtable
    patch = requests.patch(f"{base}/{record_id}",
                           headers=headers,
                           json={"fields": {"AI Diagnosis": vision_resp}})
    print("Airtable AI diagnosis status:", patch.status_code, patch.text)

    return {"status": "success"}, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))