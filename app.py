from flask import Flask, request
from openai import OpenAI
import os
import requests
import json
from triage_engine import classify_issue, should_bypass_landlord

app = Flask(__name__)

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

VONAGE_API_KEY = os.environ["VONAGE_API_KEY"]
VONAGE_API_SECRET = os.environ["VONAGE_API_SECRET"]
AIRTABLE_TOKEN = os.environ["AIRTABLE_TOKEN"]
AIRTABLE_BASE_ID = os.environ["AIRTABLE_BASE_ID"]
AIRTABLE_TABLE_NAME = "Issues"

def generate_issue_id():
    from random import randint
    return f"ISSUE-{randint(100000, 999999)}"

def get_or_create_issue(phone, message, triage):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json"
    }
    
    # Check for existing open issue
    params = {
        "filterByFormula": f"AND({{Phone}}='{phone}', OR({{Status}}='Open', {{Status}}='Escalated'))"
    }
    response = requests.get(url, headers=headers, params=params)
    records = response.json().get("records", [])

    if records:
        issue_id = records[0]["fields"].get("Issue ID", "Unknown")
        record_id = records[0]["id"]
        print(f"📌 Found existing issue ID: {issue_id}")
        return issue_id, record_id

    # Otherwise, create new issue
    issue_id = generate_issue_id()
    fields = {
        "Issue ID": issue_id,
        "Phone": phone,
        "Message": message,
        "Category": triage["category"],
        "Urgency": triage["urgency"],
        "Escalated": triage["should_escalate"],
        "Follow-ups": "\n".join(triage["followup_questions"]),
        "Status": "Open"
    }
    create_response = requests.post(url, headers=headers, json={"fields": fields})
    print("🆕 Created new issue with ID:", issue_id)
    return issue_id, create_response.json().get("id")

def log_issue_to_airtable(record_id, updates):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}/{record_id}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.patch(url, headers=headers, json={"fields": updates})
        print("Airtable update status:", response.status_code, response.text)
    except Exception as e:
        print("❌ Airtable update failed:", str(e))

@app.route("/vonage/whatsapp", methods=["POST"])
def vonage_whatsapp():
    data = request.get_json()
    print("Incoming WhatsApp:", data)

    try:
        msg = data.get("text")
        user_number = data.get("from")

        print("Message from WhatsApp user:", msg)

        triage = classify_issue(msg)
        should_escalate = should_bypass_landlord(triage)

        issue_id, record_id = get_or_create_issue(user_number, msg, triage)

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

        payload = {
            "from": {
                "type": "whatsapp",
                "number": "14157386102"
            },
            "to": {
                "type": "whatsapp",
                "number": user_number
            },
            "message": {
                "content": {
                    "type": "text",
                    "text": gpt_reply
                }
            }
        }

        response = requests.post(
            "https://messages-sandbox.nexmo.com/v0.1/messages",
            json=payload,
            auth=(VONAGE_API_KEY, VONAGE_API_SECRET)
        )

        print("Vonage send status:", response.status_code, response.text)

        log_issue_to_airtable(record_id, {"Message": msg})

        return "ok"

    except Exception as e:
        print("Error:", e)
        return "error", 500