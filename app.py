from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import openai
import os

app = Flask(__name__)
openai.api_key = os.environ.get("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")

@app.route("/sms", methods=["POST"])
def sms_reply():
    incoming_msg = request.form['Body']
    phone = request.form['From']

    # Ask GPT-4o
    completion = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are Allai, an AI assistant helping tenants report home issues. Triage the problem, ask clarifying questions, and detect urgency. Be brief, helpful, and calming."},
            {"role": "user", "content": incoming_msg}
        ]
    )

    reply = completion.choices[0].message["content"]

    # Respond to Twilio
    resp = MessagingResponse()
    resp.message(reply)
    return str(resp)
