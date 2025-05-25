import json
from datetime import datetime
import re

# Load the knowledge base
with open("knowledge_base.json") as f:
    KB = json.load(f)

ESCALATION_RULES = {
    "after_hours_start": 21,
    "after_hours_end": 7,
    "weekend": [5, 6],
    "require_media_to_confirm": False
}

def normalize(text):
    return re.sub(r"[^a-z0-9 ]", "", text.lower())

def classify_issue(text):
    text = normalize(text)
    escalation_triggers = ["escalate", "talk to someone", "talk to a human", "connect me", "urgent", "emergency", "major issue"]
    should_escalate = any(phrase in text for phrase in escalation_triggers)

    for category, data in KB.items():
        if any(keyword in text for keyword in data["keywords"]):
            emergency = should_escalate or any(trigger in text for trigger in data["emergency_triggers"])
            if emergency:
                print("⚠️ Emergency or override escalation detected. Escalating to L1.")
            return {
                "category": category,
                "urgency": "high" if emergency else "normal",
                "should_escalate": emergency,
                "followup_questions": data["followup_questions"]
            }

    return {
        "category": "other",
        "urgency": "high" if should_escalate else "normal",
        "should_escalate": should_escalate,
        "followup_questions": KB["other"]["followup_questions"]
    }

def is_after_hours():
    now = datetime.now()
    return now.hour >= ESCALATION_RULES["after_hours_start"] or now.hour < ESCALATION_RULES["after_hours_end"]

def is_weekend():
    return datetime.now().weekday() in ESCALATION_RULES["weekend"]

def should_bypass_landlord(escalation_info, media_present=False):
    if escalation_info["should_escalate"]:
        print("⚠️ Escalation due to emergency or override condition.")
        return True
    if is_after_hours() or is_weekend():
        print("⏰ Escalation due to time condition (after-hours or weekend).")
        return True
    if ESCALATION_RULES["require_media_to_confirm"] and not media_present:
        print("📸 Escalation requires media confirmation but none provided.")
        return False
    return False