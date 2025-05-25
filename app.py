from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import openai
import os

app = Flask(__name__)
openai.api_key = os.environ.get("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")

@app.route("/", methods=["GET"])
def index():
    return "Allai webhook is running! ✅"
    
@app.route("/sms", methods=["POST"])
def sms_reply():
    incoming_msg = request.form.get("Body", "")
    phone = request.form.get("From", "")

    print("Received message:", incoming_msg)

    try:
        completion = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are Allai, a helpful AI assistant for tenants..."},
                {"role": "user", "content": incoming_msg}
            ]
        )
        reply = completion.choices[0].message["content"]
        print("AI Response:", reply)

    except Exception as e:
        print("❌ OpenAI API Error:", str(e))  # This will show you exactly what went wrong
        reply = "Sorry, something went wrong while processing your request."

    resp = MessagingResponse()
    resp.message(reply)
    return str(resp)
