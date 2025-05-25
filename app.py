from flask import request
from openai import OpenAI
import os
import requests

client = OpenAI(api_key=os.environ["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"])

VONAGE_API_KEY = os.environ["e71e8143"]
VONAGE_API_SECRET = os.environ["49513061"]

@app.route("/vonage/whatsapp", methods=["POST"])
def vonage_whatsapp():
    data = request.get_json()
    print("Incoming WhatsApp:", data)

    # Extract message and sender
    msg = data['message']['content']['text']
    to = data['from']['number']
    from_ = data['to']['number']

    # Get AI reply
    gpt_reply = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are Allai, a helpful assistant for tenant maintenance issues."},
            {"role": "user", "content": msg}
        ]
    ).choices[0].message.content

    # Send back reply via Vonage Messages API
    response = requests.post("https://api.nexmo.com/v0.1/messages", json={
        "from": {"type": "whatsapp", "number": from_},
        "to": {"type": "whatsapp", "number": to},
        "message": {
            "content": {
                "type": "text",
                "text": gpt_reply
            }
        }
    }, auth=(VONAGE_API_KEY, VONAGE_API_SECRET))

    print("Vonage send response:", response.status_code, response.text)
    return "ok"
