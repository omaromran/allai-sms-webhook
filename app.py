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

    try:
        completion = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are Allai, an AI assistant helping tenants report maintenance issues..."},
                {"role": "user", "content": incoming_msg}
            ]
        )
        reply = completion.choices[0].message["content"]

    except Exception as e:
        print("Error from OpenAI:", e)
        reply = "Sorry, something went wrong while processing your request. Please try again later."

    resp = MessagingResponse()
    resp.message(reply)
    return str(resp)
