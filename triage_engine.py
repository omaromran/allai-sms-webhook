import json
from datetime import datetime
import re

# Load the knowledge base JSON
with open("knowledge_base.json") as f:
    KB = json.load(f)

# Configurable rules
ESCALATION_RULES = {
    "after_hours_start": 21,   # 9 PM
    "after_hours_end": 7,      # 7 AM
    "weekend": [5, 6],         # Saturday, Sunday
    "require_media_to_confirm": False
}

def normalize(text):
    return re.sub(r"[^a-z0-9 ]", "", text.lower())

def classify_issue(text):
    text = normalize(text)
    for category, data in KB.items():
        if any(keyword in text for keyword in data["keywords"]):
            emergency = any(trigger in text for trigger in data["emergency_triggers"])
            if emergency:
                print("⚠️ Emergency trigger detected. Escalating to L1.")
            return {
                "category": category,
                "urgency": "high" if emergency else "normal",
                "should_escalate": emergency,
                "followup_questions": data["followup_questions"]
            }
    return {
        "category": "other",
        "urgency": "normal",
        "should_escalate": False,
        "followup_questions": KB["other"]["followup_questions"]
    }

def is_after_hours():
    now = datetime.now()
    return now.hour >= ESCALATION_RULES["after_hours_start"] or now.hour < ESCALATION_RULES["after_hours_end"]

def is_weekend():
    return datetime.now().weekday() in ESCALATION_RULES["weekend"]

def should_bypass_landlord(triage_result, media_present=False):
    if triage_result["should_escalate"]:
        print("⚠️ Escalation due to emergency condition.")
        return True
    if is_after_hours() or is_weekend():
        print("⏰ Escalation due to time condition (after-hours or weekend).")
        return True
    if ESCALATION_RULES["require_media_to_confirm"] and not media_present:
        print("📸 Escalation requires media confirmation but none provided.")
        return False
    return False
