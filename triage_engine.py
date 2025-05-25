import json
from datetime import datetime
import re

# Load knowledge base (assumes it's in same directory)
with open("knowledge_base.json") as f:
    KB = json.load(f)

ESCALATION_RULES = {
    "after_hours_start": 21,   # 9 PM
    "after_hours_end": 7,      # 7 AM
    "weekend": [5, 6],         # Saturday = 5, Sunday = 6
    "require_media_to_confirm": False
}

def normalize(text):
    return re.sub(r"[^a-z0-9 ]", "", text.lower())

def classify_issue(text):
    text = normalize(text)
    for category, data in KB.items():
        if any(keyword in text for keyword in data["keywords"]):
            emergency = any(trigger in text for trigger in data["emergency_triggers"])
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

def should_bypass_landlord(escalation_info, media_present=False):
    if escalation_info["should_escalate"]:
        return True
    if is_after_hours() or is_weekend():
        return True
    if ESCALATION_RULES["require_media_to_confirm"] and not media_present:
        return False
    return False
