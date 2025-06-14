# app.py
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import os, time, requests, json
from triage_engine import classify_issue, should_bypass_landlord
from datetime import datetime
import smtplib
from email.mime.text import MIMEText

app = Flask(__name__)
CORS(app)

# ---- CONFIG & CLIENTS ----
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

VONAGE_API_KEY    = os.environ["VONAGE_API_KEY"]
VONAGE_API_SECRET = os.environ["VONAGE_API_SECRET"]
PAGE_ID           = os.environ["MESSENGER_PAGE_ID"]  # your FB page ID
AIRTABLE_TOKEN    = os.environ["AIRTABLE_TOKEN"]
AIRTABLE_BASE_ID  = os.environ["AIRTABLE_BASE_ID"]
AIRTABLE_TABLE    = "Issues"

GMAIL_USER    = os.environ["GMAIL_USER"]
GMAIL_PASS    = os.environ["GMAIL_APP_PASS"]
L1_EMAIL      = os.environ.get("L1_EMAIL","omranomar1@gmail.com")

VISUAL_CATEGORIES = {"hvac","plumbing","pest","appliance","other"}

# ---- HELPERS ----
def generate_issue_id():
    from random import randint
    return f"ISSUE-{randint(100000,999999)}"

def is_new_issue(msg):
    msg=msg.lower()
    return any(p in msg for p in ["new issue","another issue","different problem","new problem"])

def is_resolved(msg):
    msg=msg.lower()
    return any(p in msg for p in ["fixed","resolved","no longer","solved","it’s all good"])

def get_or_create_issue(phone,msg):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE}"
    hdr = {"Authorization":f"Bearer {AIRTABLE_TOKEN}","Content-Type":"application/json"}
    resp = requests.get(url,headers=hdr,params={
        "filterByFormula":f"AND({{Phone}}='{phone}',OR({{Status}}='Open',{{Status}}='Escalated'))"
    }).json().get("records",[])
    if resp and not is_new_issue(msg):
        r = resp[0]
        return r["fields"]["Issue ID"],r["id"],False,r["fields"].get("Category")
    # else new
    return generate_issue_id(),None,True,None

def notify_l1(issue_id,summary,category,urgency,record_id,unit):
    link=f"https://airtable.com/{AIRTABLE_BASE_ID}/{record_id}"
    body=f"""🚨 Escalated Issue {issue_id}
Unit: {unit}
Category: {category}
Urgency: {urgency}

{summary}

↪️ {link}"""
    m=MIMEText(body)
    m["Subject"]=f"🚨 Escalated {issue_id}"
    m["From"]=GMAIL_USER
    m["To"]=L1_EMAIL
    with smtplib.SMTP_SSL("smtp.gmail.com",465) as s:
        s.login(GMAIL_USER,GMAIL_PASS)
        s.send_message(m)
    print("📧 L1 email sent")

def get_unit(phone):
    url=f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/Tenants"
    hdr={"Authorization":f"Bearer {AIRTABLE_TOKEN}","Content-Type":"application/json"}
    recs=requests.get(url,headers=hdr,params={
        "filterByFormula":f"{{Phone}}='{phone}'"
    }).json().get("records",[])
    return recs[0]["fields"].get("Unit","Unknown") if recs else "Unknown"

def log_airtable(record_id,fields):
    url=f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE}/{record_id}"
    hdr={"Authorization":f"Bearer {AIRTABLE_TOKEN}","Content-Type":"application/json"}
    r=requests.patch(url,headers=hdr,json={"fields":fields})
    print("Airtable update:",r.status_code,r.text)

def send_vonage(recipient_id,text,channel="messenger"):
    if channel=="messenger":
        payload={
            "from": {"type":"messenger","id":PAGE_ID},
            "to":   {"type":"messenger","id":recipient_id},
            "message": {"content":{"type":"text","text":text}}
        }
    else:  # whatsapp fallback
        payload={
            "from": {"type":"whatsapp","number":os.environ["WHATSAPP_FROM"]},
            "to":   {"type":"whatsapp","number":recipient_id},
            "message": {"content":{"type":"text","text":text}}
        }
    r=requests.post(
        "https://api.nexmo.com/v0.1/messages",
        json=payload,
        auth=(VONAGE_API_KEY,VONAGE_API_SECRET)
    )
    print("Vonage send:",r.status_code,r.text)

# ---- MAIN INCOMING MSGS ----
@app.route("/messages", methods=["POST"])
def incoming():
    data = request.get_json()
    print("Incoming:",data)
    msg  = data.get("text","")
    usr  = data.get("from")
    chan = data.get("channel")
    print("User says:",msg)
    try:
        # find or new
        issue_id,rec_id,is_new,existing_cat = get_or_create_issue(usr,msg)
        # classify
        triage = classify_issue(msg) if is_new else classify_issue(msg)
        # create record if new
        if is_new:
            rec_fields={
                "Issue ID":issue_id,
                "Phone":usr,
                "Message Summary":msg[:50],
                "Message":msg,
                "Category":triage["category"],
                "Urgency":triage["urgency"],
                "Escalated":triage["should_escalate"],
                "Follow-ups":"\n".join(triage["followup_questions"]),
                "Status":"Open"
            }
            url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE}"
            hdr = {"Authorization":f"Bearer {AIRTABLE_TOKEN}","Content-Type":"application/json"}
            res = requests.post(url,headers=hdr,json={"fields":rec_fields}).json()
            rec_id = res["id"]
            print("🆕 Created",issue_id)
        # check media flag
        r = requests.get(
            f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE}/{rec_id}",
            headers={"Authorization":f"Bearer {AIRTABLE_TOKEN}"}
        ).json().get("fields",{})
        media_flag = r.get("Media Submitted",False)
        # escalate?
        do_esc = should_bypass_landlord(triage,media_present=media_flag)
        if do_esc:
            unit = get_unit(usr)
            notify_l1(issue_id,msg[:50],triage["category"],triage["urgency"],rec_id,unit)

        # resolved?
        if is_resolved(msg):
            log_airtable(rec_id,{"Status":"Resolved","Message":msg})
            reply=f"👍 Marked {issue_id} resolved."
        else:
            # ask/answer
            instr = ("🚨 This has been escalated." if do_esc
                     else f"I understand you're reporting {triage['category']}.")
            prompt = (
                f"You are Allai, a maintenance assistant.\n"
                f"Category: {triage['category']}\n"
                f"Urgency: {triage['urgency']}\n"
                f"{instr}\n"
                f"Ask:\n- "+" \n- ".join(triage["followup_questions"])
            )
            gpt = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role":"system","content":prompt},
                    {"role":"user","content":msg}
                ]
            ).choices[0].message.content
            reply = gpt
            # if we can show upload link
            if triage["category"] in VISUAL_CATEGORIES and not media_flag:
                reply += (
                    f"\n\n📸 Please upload a **photo** here:\n"
                    f"https://allai-upload.web.app?issue_id={issue_id}\n"
                    "Then return to chat."
                )
            log_airtable(rec_id,{"Message":msg})

        # send back
        send_vonage(usr,reply,channel=chan)
        return "ok",200

    except Exception as e:
        print("Error:",e)
        return "error",500

# ---- MEDIA UPLOAD CALLBACK ----
@app.route("/media-upload", methods=["POST", "OPTIONS"])
def media_upload():
    # CORS preflight
    if request.method == "OPTIONS":
        return "", 200

    data = request.get_json()
    issue_id   = data.get("issue_id")
    media_urls = data.get("media_urls", [])
    if not issue_id or not media_urls:
        return jsonify(error="Missing issue_id or media_urls"), 400

    # find the record
    base = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE}"
    hdr  = {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json"
    }
    recs = requests.get(
        base,
        headers=hdr,
        params={ "filterByFormula": f"{{Issue ID}}='{issue_id}'" }
    ).json().get("records", [])
    if not recs:
        return jsonify(error="Issue ID not found"), 404

    rec    = recs[0]
    rec_id = rec["id"]
    user_phone = rec["fields"].get("Phone")

    # attach media & flag
    attachments = [{"url": u} for u in media_urls]
    requests.patch(
        f"{base}/{rec_id}",
        headers=hdr,
        json={ "fields": { "Media": attachments, "Media Submitted": True } }
    )
    print("Media uploaded to Airtable")

    # tiny delay
    time.sleep(1)

    # build the vision messages
    img_url = media_urls[0]
    messages = [
        {
            "role": "system",
            "content": "You are an expert HVAC/home-maintenance technician. Diagnose what’s wrong in the image and explain how to fix it."
        },
        {
            "role": "user",
            "content": {
                "type": "image_url",
                "image_url": img_url
            }
        }
    ]

    # call GPT-4o vision
    vision_resp = client.chat.completions.create(
        model="gpt-4o",
        messages=messages
    ).choices[0].message.content

    # write diagnosis back
    requests.patch(
        f"{base}/{rec_id}",
        headers=hdr,
        json={ "fields": { "AI Diagnosis": vision_resp } }
    )
    print("AI diagnosis written to Airtable")

    # immediately notify the user
    followup = (
        f"✅ Got the photo! Here’s what I see:\n\n{vision_resp}\n\n"
        "Feel free to return to this chat if you have any more questions."
    )
    send_vonage(user_phone, followup, channel="messenger")

    return jsonify(status="success"), 200