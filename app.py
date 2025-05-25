from flask import Flask, request
from openai import OpenAI
import os
import requests
import json

app = Flask(__name__)

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

VONAGE_API_KEY = os.environ["VONAGE_API_KEY"]
VONAGE_API_SECRET = os.environ["VONAGE_API_SECRET"]

# Load knowledge base once at startup
with open("knowledge_base.json") as f:
    KB = json.load(f)

def classify_issue(msg, kb):
    msg_lower = msg.lower()
    for category, info in kb.items():
        if any(word in msg_lower for word in info["keywords"]):
            emergency = any(phrase in msg_lower for phrase in info["emergency_phrases"])
            return category, info["questions"], emergency
    return "other", ["Can you tell me more about the issue?"], False

@app.route("/vonage/whatsapp", methods=["POST"])
def vonage_whatsapp():
    data = request.get_json()
    print("Incoming WhatsApp:", data)

    try:
        msg = data.get("text")
        user_number = data.get("from")

        print("Message from WhatsApp user:", msg)

        # Triage via knowledge base
        category, questions, is_urgent = classify_issue(msg, KB)
        triage_prompt = (
            f"You are Allai, a tenant assistant trained in property maintenance triage.\n"
            f"This issue appears to relate to: {category}.\n"
            f"It {'is' if is_urgent else 'is not'} urgent.\n"
            f"Ask the following questions to help clarify the issue:\n"
            f"- " + "\n- ".join(questions)
        )

        # GPT-4o response
        gpt_reply = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": triage_prompt},
                {"role": "user", "content": msg}
            ]
        ).choices[0].message.content

        # Send GPT reply to WhatsApp
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
