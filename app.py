from flask import Flask, request
from openai import OpenAI
import os
import requests
import json
from datetime import datetime

app = Flask(__name__)

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

VONAGE_API_KEY = os.environ["VONAGE_API_KEY"]
VONAGE_API_SECRET = os.environ["VONAGE_API_SECRET"]

# Load knowledge base
with open("knowledge_base.json") as f:
    KB = json.load(f)

ESCALATION_RULES = {
    "after_hours_start": 21,
    "after_hours_end": 7,
    "weekend": [5, 6],
    "require_media_to_confirm": False
}

def classify_issue(text):
    text = text.lower()
    for category, data in KB.items():
        if any(keyword in text for keyword in data["keywords"]):
            emergency = any(trigger in text for trigger in data["emergency_triggers"])
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
        return True
    if is_after_hours() or is_weekend():
        return True
    if ESCALATION_RULES["require_media_to_confirm"] and not media_present:
        return False
    return False

@app.route("/vonage/whatsapp", methods=["POST"])
def vonage_whatsapp():
    data = request.get_json()
    print("Incoming WhatsApp:", data)

    try:
        msg = data.get("text")
        user_number = data.get("from")

        print("Message from WhatsApp user:", msg)

        # Classify issue
        triage = classify_issue(msg)
        should_escalate = should_bypass_landlord(triage)

        # Escalation-based language
        escalation_instruction = (
            "This issue is urgent and requires escalation to a human. "
            "Let the tenant know it’s being escalated. Be clear and calm."
            if should_escalate else
            "This issue is not considered urgent. Ask follow-up questions to better understand the situation."
        )
        
        # GPT prompt
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

        # Send AI reply back to WhatsApp
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
        return "ok"

    except Exception as e:
        print("Error:", e)
        return "error", 500
