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

        # Generate GPT response
        gpt_reply = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are Allai, an assistant that helps tenants report maintenance issues."},
                {"role": "user", "content": msg}
            ]
        ).choices[0].message.content

        # Send AI reply back to WhatsApp via Vonage API
        response = requests.post("https://api.nexmo.com/v0.1/messages", json={
            "from": {"type": "whatsapp", "number": "+14157386170"},
            "to": {"type": "whatsapp", "number": user_number},
            "message": {
                "content": {
                    "type": "text",
                    "text": gpt_reply
                }
            }
        }, auth=(os.environ["VONAGE_API_KEY"], os.environ["VONAGE_API_SECRET"]))

        print("Vonage send status:", response.status_code, response.text)
        return "ok"

    except Exception as e:
        print("Error:", e)
        return "error", 500
