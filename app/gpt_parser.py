# gpt_parser.py
import os
import requests
import json
import re
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

GPT_API_KEY = os.getenv("OPENAI_API_KEY")
if not GPT_API_KEY:
    raise ValueError("❌ OPENAI_API_KEY not found in environment variables")


def parse_lead_info(message: str):
    """
    Uses GPT to extract structured lead info from both natural language and comma-separated formats.
    """
    prompt = f"""
You are an expert CRM assistant. Extract the following fields from the user's message.

The input message can be in various formats:
1. A natural sentence: "There is a lead from ABC Pvt Ltd, contact is Ramesh (9876543210), assign to Banwari, source is referral"
2. A comma-separated format where the assignee comes before the source: "Mohini Printers, mohini, 7867564534, Banwari, referral"
3. A format where the source is explicitly mentioned with a label: "ABC Pvt Ltd, Ramesh, 9876543210, Source Referral, assign to Banwari"
4. A simple comma-separated format without an assignee: "ABC Pvt Ltd, Ramesh, 9876543210, referral"

👉 **Parsing Rules for comma-separated values without labels:**
- If 5 values are provided, the order is: `company_name`, `contact_name`, `phone`, `assigned_to`, `source`.
- If 4 values are provided, the order is: `company_name`, `contact_name`, `phone`, `source`.
- If the phrase "assign to" is present, extract the assignee name or phone number following it, regardless of position.

👉 **Defaults:**
- If "source" is not mentioned, set it to "whatsapp".
- If "assigned_to" is not mentioned, leave it as null in the JSON output.

Please extract and return the following fields:

Required Fields:
- "company_name"
- "contact_name"
- "phone"
- "source" (set default to "whatsapp" if not provided)
- "assigned_to" (Extract if present. Otherwise leave null)

Optional Fields:
- "email"
- "address"
- "team_size"
- "segment"
- "remark"
- "product"

Return only JSON. Do not add explanations.

User Message:
\"{message}\"    
"""

    headers = {
        "Authorization": f"Bearer {GPT_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "response_format": {"type": "json_object"}
    }

    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=20
        )

        if response.status_code != 200:
            logger.error("❌ GPT API error (%s): %s", response.status_code, response.text)
            return {}, f"❌ GPT API failed: {response.status_code}"

        result_content = response.json()["choices"][0]["message"]["content"]
        logger.info(f"🔍 Raw GPT Response: {result_content}")

        try:
            data = json.loads(result_content)
        except json.JSONDecodeError:
            logger.error("❌ GPT returned invalid JSON")
            return {}, "❌ GPT returned invalid JSON"

        if isinstance(data, dict) and data.get("missing_fields"):
            return data, f"❗ Missing fields: {', '.join(data['missing_fields'])}. Please provide them."

        if not data.get("source"):
            data["source"] = "whatsapp"

        # --- REMOVED THIS LINE ---
        # The logic below will correctly check if assigned_to is missing.
        # if not data.get("assigned_to"):
        #     data["assigned_to"] = "8878433436"

        required = ["company_name", "contact_name", "phone", "source", "assigned_to"]
        missing_final = [f for f in required if not data.get(f)]
        if missing_final:
            return {"missing_fields": missing_final}, f"❗ Missing fields: {', '.join(missing_final)}. Please provide them."

        return data, "✅ Lead info parsed successfully."

    except requests.exceptions.RequestException as e:
        logger.error(f"❌ GPT API request error: {e}")
        return {}, "❌ Could not connect to the AI service."
    except Exception as e:
        logger.error(f"❌ GPT processing error: {e}")
        return {}, "❌ An unexpected error occurred."


def parse_update_fields(msg_text: str):
    """
    Extract fields for updating a lead from either comma-separated values or sentence.
    Returns a dictionary of field: value pairs.
    """
    update_data = {}
    msg_text = msg_text.strip().lower()

    field_map = {
        "company": "company_name",
        "contact": "contact_name",
        "name": "contact_name",
        "phone": "phone",
        "mobile": "phone",
        "email": "email",
        "address": "address",
        "city": "address",
        "location": "address",
        "team": "team_size",
        "size": "team_size",
        "source": "source",
        "segment": "segment",
        "remark": "remark",
        "status": "status",
        "assign": "assigned_to",
        "assigned": "assigned_to"
    }

    for key, field in field_map.items():
        if key in msg_text:
            match = re.search(rf"{key}\s*(is|:)?\s*([a-zA-Z0-9@_.\- ]+)", msg_text)
            if match:
                value = match.group(2).strip()
                update_data[field] = value

    if len(update_data) < 3 and ',' in msg_text:
        parts = [p.strip() for p in msg_text.split(',')]
        probable_fields = [
            "company_name", "contact_name", "phone", "address", "team_size", "segment",
            "email", "remark", "status", "assigned_to"
        ]
        for i in range(min(len(parts), len(probable_fields))):
            update_data[probable_fields[i]] = parts[i]

    return update_data


def parse_update_company(message: str) -> str:
    """
    Extracts the company name from messages like "Lead qualified for Parksons" or just "Parksons".
    """
    msg = message.strip()
    lowered_msg = msg.lower()

    # Pattern to find company name after keywords like 'for' or 'is'
    match = re.search(r"(?:qualified\s+for|company\s+is|for)\s+([A-Za-z0-9\s&.'-]+)", lowered_msg)
    if match:
        # Use .title() to properly capitalize company names like "Parksons"
        return match.group(1).strip().title()

    # If no pattern matches, and the message is short, assume the whole message is the company name.
    # This is crucial for handling the follow-up case where the user just sends "Parksons".
    keywords_to_avoid = [
        "lead", "qualified", "demo", "meeting", "update", "schedule", "new", "reminder", "done"
    ]
    # Check if the message is short (e.g., up to 5 words) and doesn't contain common command keywords.
    if 1 <= len(msg.split()) <= 5 and not any(word in lowered_msg for word in keywords_to_avoid):
        return msg.title()

    return ""


def parse_intent_and_fields(message: str):
    """
    Detects user's intent using fast regex-based rules.
    """
    lowered = message.lower()

    if re.search(r"lead\s+is\s+qualified|qualified\s+for|is\s+qualified|lead qualified", lowered):
        return "qualify_lead", {}

    if re.search(r"schedule.+quotation", lowered): return "schedule_quotation", {}
    if re.search(r"schedule.+demo", lowered): return "schedule_demo", {}
    if re.search(r"schedule.+meeting|meeting.+schedule", lowered): return "schedule_meeting", {}
    if re.search(r"reassign", lowered): return "reassign_task", {}
    if re.search(r"remind me|set reminder", lowered): return "reminder", {}
    if re.search(r"feedback for", lowered) or re.search(r"meeting done", lowered): return "feedback", {}

    if re.search(r"new lead|there is a lead|add lead", lowered) or ("lead" in lowered and "tell" in lowered):
        return "new_lead", {}

    if message.count(",") >= 3:
        return "new_lead", {}

    if re.search(r"demo (is )?done|demo completed|demo finished|demo ho gya|demo ho gaya", lowered):
        return "demo_done", {}

    return "unknown", {}