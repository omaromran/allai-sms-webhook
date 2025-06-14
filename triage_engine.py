# ✅ FILE: triage_engine.py

import os
import json
import difflib
from datetime import datetime

TRIAGE_DATA_DIR = "triage_data"
CATEGORY_DATA = {}
ESCALATION_RULES = {}

# Load all triage category JSONs
for filename in os.listdir(TRIAGE_DATA_DIR):
    if filename.endswith(".json") and filename != "escalation_rules.json":
        category = filename.replace(".json", "")
        with open(os.path.join(TRIAGE_DATA_DIR, filename)) as f:
            CATEGORY_DATA[category] = json.load(f)

# Load escalation rules
try:
    with open(os.path.join(TRIAGE_DATA_DIR, "escalation_rules.json")) as f:
        ESCALATION_RULES = json.load(f)
except Exception as e:
    print("⚠️ Failed to load escalation_rules.json:", e)


def fuzzy_match(message, examples, threshold=0.6):
    for example in examples:
        similarity = difflib.SequenceMatcher(None, example.lower(), message.lower()).ratio()
        if similarity >= threshold:
            return True
    return False

def clean_message(text):
    text = text.lower().strip()
    if text.startswith("new issue:"):
        text = text.replace("new issue:", "").strip()
    return text

def classify_issue(message):
    message = clean_message(message)
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

    urgency = "high" if any(word in message for word in ["urgent", "asap", "immediately", "critical", "major"]) else "normal"

    triage_info = {
        "category": best_category,
        "cluster": best_cluster.get("name"),
        "urgency": urgency,
        "followup_questions": best_cluster.get("triage_questions", []),
        "message": message
    }

    triage_info["should_escalate"] = should_bypass_landlord(triage_info)
    return triage_info

def should_bypass_landlord(triage_info, media_present=False):
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

    # Remove time-based escalation logic for now

    if urgency == "high" and not media_present:
        print("📸 Urgent issue reported without media — escalating for review")
        return True

    print("✅ No escalation triggered.")
    return False