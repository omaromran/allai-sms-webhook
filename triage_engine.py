from flask import Flask, request
from openai import OpenAI
import os
import requests
import json
from datetime import datetime
import re

app = Flask(__name__)

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

VONAGE_API_KEY = os.environ["VONAGE_API_KEY"]
VONAGE_API_SECRET = os.environ["VONAGE_API_SECRET"]
AIRTABLE_TOKEN = os.environ["AIRTABLE_TOKEN"]
AIRTABLE_BASE_ID = os.environ["AIRTABLE_BASE_ID"]
AIRTABLE_TABLE_NAME = "Issues"

# Load knowledge base
with open("knowledge_base.json") as f:
    KB = json.load(f)

ESCALATION_RULES = {
    "after_hours_start": 21,
    "after_hours_end": 7,
    "weekend": [5, 6],
    "require_media_to_confirm": False
}

def normalize(text):
    return re.sub(r"[^a-z0-9 ]", "", text.lower())

def classify_issue(text):
    text = normalize(text)
    for category, data in KB.items():
        if any(keyword in text for keyword in data["keywords"]):
            emergency = any(trigger in text for trigger in data["emergency_triggers"])
            if emergency:
                print("⚠️ Emergency trigger detected. Escalating to L1.")
            return {
                "category": category,
                "urgency": "high" if emergency else "normal",
                "should_escalate": emergency,
                "followup_questions": data["followup_questions"]
            }
    return {
        "category": "other",
        "urgency": "normal",
        "should_escalate": False,
        "followup_questions": KB["other"]["followup_questions"]
    }

def is_after_hours():
    now = datetime.now()
    return now.hour >= ESCALATION_RULES["after_hours_start"] or now.hour < ESCALATION_RULES["after_hours_end"]

def is_weekend():
    return datetime.now().weekday() in ESCALATION_RULES["weekend"]

def should_bypass_landlord(escalation_info, media_present=False):
    if escalation_info["should_escalate"]:
        print("⚠️ Escalation due to emergency condition.")
        return True
    if is_after_hours() or is_weekend():
        print("⏰ Escalation due to time condition (after-hours or weekend).")
        return True
    if ESCALATION_RULES["require_media_to_confirm"] and not media_present:
        print("📸 Escalation requires media confirmation but none provided.")
        return False
    return False

def log_issue_to_airtable(phone, message, category, urgency, escalated, followups, media_links=[]):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json"
    }
    fields = {
        "Message Summary": message[:50],
        "Phone": phone,
        "Message": message,
        "Category": category,
        "Urgency": urgency,
        "Escalated": escalated,
        "Follow-ups": "\n".join(followups)
    }
    if media_links:
        fields["Media"] = [{"url": link} for link in media_links]

    response = requests.post(url, headers=headers, json={"fields": fields})
    print("Airtable log status:", response.status_code, response.text)

@app.route("/vonage/whatsapp", methods=["POST"])
def vonage_whatsapp():
    data = request.get_json()
    print("Incoming WhatsApp:", data)

    try:
        msg = data.get("text")
        user_number = data.get("from")
        media_links = data.get("media_urls", [])  # Placeholder for later integration

        print("Message from WhatsApp user:", msg)

        triage = classify_issue(msg)
        should_escalate = should_bypass_landlord(triage, media_present=bool(media_links))

        escalation_instruction = (
            "This issue is urgent and requires escalation to a human. Let the tenant know it’s being escalated. Be clear and calm."
            if should_escalate else
            "This issue is not considered urgent. Ask follow-up questions to better understand the situation."
        )

        triage_prompt = (
            f"You are Allai, a tenant assistant trained in property maintenance triage.\n"
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

        log_issue_to_airtable(user_number, msg, triage["category"], triage["urgency"], should_escalate, triage["followup_questions"], media_links)

        return "ok"

    except Exception as e:
        print("Error:", e)
        return "error", 500
