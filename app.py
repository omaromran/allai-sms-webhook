from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from openai import OpenAI
import os
import requests


app = Flask(__name__)

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

VONAGE_API_KEY = os.environ["VONAGE_API_KEY"]
VONAGE_API_SECRET = os.environ["VONAGE_API_SECRET"]

@app.route("/vonage/whatsapp", methods=["POST"])
def vonage_whatsapp():
    data = request.get_json()
    print("Incoming WhatsApp:", data)

    try:
        # Vonage sends message text directly as 'text'
        msg = data.get("text")
        user_number = data.get("from")

        print("Message from WhatsApp user:", msg)

        # Generate GPT-4o response
        gpt_reply = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are Allai, a helpful, friendly AI assistant for home maintenance. "
                "Introduce yourself only on the first message of a conversation."
                "If the tenant has already sent a message and you've replied, do not reintroduce yourself."
                "Your job is to classify issues (e.g., plumbing, HVAC, electrical), assess urgency, and guide next steps."
                "If the issue is urgent (e.g., fire, gas, flooding, sparks, broken heater), escalate it."
                "If it's not urgent, ask 1–2 helpful follow-up questions to clarify."
                "Be warm, clear, and concise."},
                {"role": "user", "content": msg}
            ]
        ).choices[0].message.content

        # Build proper payload
        payload = {
            "from": {
                "type": "whatsapp",
                "number": "14157386102"  # ✅ Your exact Vonage sandbox number
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

        print("User Number:", user_number)

        # Send reply through Vonage Sandbox API
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
