# triage_engine.py
import json
import os
from openai import OpenAI
from datetime import datetime
from dotenv import load_dotenv
import difflib

TRIAGE_DATA_DIR = "triage_data"
CATEGORY_DATA = {}
ESCALATION_RULES = {}

load_dotenv()
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

# Load triage category data
for filename in os.listdir(TRIAGE_DATA_DIR):
    if filename.endswith(".json") and filename != "escalation_rules.json":
        category = filename.replace(".json", "")
        with open(os.path.join(TRIAGE_DATA_DIR, filename)) as f:
            CATEGORY_DATA[category] = json.load(f)

# Load escalation rules
escalation_file = os.path.join(TRIAGE_DATA_DIR, "escalation_rules.json")
if os.path.exists(escalation_file):
    with open(escalation_file) as f:
        ESCALATION_RULES = json.load(f)

def fuzzy_match(message, examples, threshold=0.6):
    for example in examples:
        similarity = difflib.SequenceMatcher(None, example.lower(), message.lower()).ratio()
        if similarity >= threshold:
            return True
    return False

def assess_urgency_with_openai(message):
    prompt = (
        "You are an AI assistant helping classify the urgency of maintenance requests from tenants. "
        "Reply with only one word: 'high' if the issue needs immediate attention (e.g., danger, no power, gas, fire, water flood, health risk), or 'normal' if it can wait.\n\n"
        f"Tenant message: \"{message}\""
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Return only one word: 'high' or 'normal'."},
                {"role": "user", "content": prompt}
            ]
        )
        urgency = response.choices[0].message.content.strip().lower()
        if urgency not in ["high", "normal"]:
            return "normal"
        return urgency
    except Exception as e:
        print("❌ OpenAI urgency classification failed:", str(e))
        return "normal"

def classify_issue(message):
    message_lower = message.lower()
    best_category = "other"
    best_cluster = None

    for category, data in CATEGORY_DATA.items():
        for cluster in data.get("clusters", []):
            if fuzzy_match(message, cluster.get("examples", [])):
                best_category = category
                best_cluster = cluster
                break
        if best_cluster:
            break

    if not best_cluster:
        best_cluster = {
            "name": "Unknown",
            "examples": [],
            "triage_questions": ["Can you tell me more about the issue?"],
            "escalation_rules": {},
        }

    urgency = assess_urgency_with_openai(message)

    triage_info = {
        "category": best_category,
        "cluster": best_cluster.get("name"),
        "urgency": urgency,
        "followup_questions": best_cluster.get("triage_questions", []),
        "message": message,
    }

    triage_info["should_escalate"] = should_bypass_landlord(triage_info)

    return triage_info

def should_bypass_landlord(triage_info, media_present=False):
    global ESCALATION_RULES
    message = triage_info.get("message", "").lower()
    urgency = triage_info.get("urgency", "normal")

    if not message:
        print("⚠️ Warning: 'message' key missing from triage_info.")

    print("\n🔍 Escalation Debug Info:")
    print(f"Message: {message}")
    print(f"Urgency: {urgency}")
    print(f"Media Present: {media_present}")

    for keyword in ESCALATION_RULES.get("emergency_keywords", []):
        if keyword.lower() in message:
            print(f"⚠️ Emergency keyword triggered: '{keyword}'")
            return True

    for phrase in ESCALATION_RULES.get("urgency_phrases", []):
        if phrase.lower() in message:
            print(f"⚠️ Urgency phrase triggered: '{phrase}'")
            return True

    if urgency == "high" and not media_present:
        print("📸 Urgent issue reported without media — escalating for review")
        return True

    print("✅ No escalation triggered.")
    return False