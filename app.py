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

    print("📬 Sending issue to Airtable...")
    print("🛠 Airtable payload:", json.dumps(fields, indent=2))

    try:
        response = requests.post(url, headers=headers, json={"fields": fields})
        print("Airtable log status:", response.status_code, response.text)
    except Exception as e:
        print("❌ Airtable logging failed:", str(e))

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

        escalation_instruction = (
            "This issue is urgent and requires escalation to a human. Let the tenant know it’s being escalated. Be clear and calm."
            if should_escalate else
            "This issue is not considered urgent. Ask follow-up questions to better understand the situation."
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

        log_issue_to_airtable(user_number, msg, triage["category"], triage["urgency"], should_escalate, triage["followup_questions"])

        return "ok"

    except Exception as e:
        print("Error:", e)
        return "error", 500
