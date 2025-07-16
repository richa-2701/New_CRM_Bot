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

The input message can be:
1. A natural sentence like: "There is a lead from ABC Pvt Ltd, contact is Ramesh (9876543210), city Jaipur, product Inventory Software, assign to Banwari"
2. OR a simple comma-separated format like: "ABC Pvt Ltd, Ramesh, 9876543210, Jaipur, Inventory Software, Banwari"
3. OR a format like: "ABC Pvt Ltd, Ramesh, 9876543210, referral, assign to Banwari"

👉 If the phrase "assign to" is present, extract the assignee name or phone number following it.
👉 If only 4 values are given without labels, treat them in order: company_name, contact_name, phone, source.
👉 Always default "source" to "whatsapp" if not mentioned.

Please extract and return the following fields:

Required Fields:
- "company_name"
- "contact_name"
- "phone"
- "source" (set default to "whatsapp" if not provided)

Optional Fields:
- "email"
- "address"
- "team_size"
- "segment"
- "remark"
- "product"
- "city"
- "assigned_to" (Extract if present. Otherwise leave null)

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

        # Handle missing required fields returned by GPT explicitly
        if isinstance(data, dict) and data.get("missing_fields"):
            return data, f"❗ Missing fields: {', '.join(data['missing_fields'])}. Please provide them."

        # Ensure source defaults to "whatsapp"
        if not data.get("source"):
            data["source"] = "whatsapp"

        # Ensure assigned_to defaults to "8878433436" if not provided
        if not data.get("assigned_to"):
            data["assigned_to"] = "8878433436"

        # Final check for required fields
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


def parse_intent_and_fields(message: str):
    """
    Detects user's intent using fast regex-based rules.
    """
    lowered = message.lower()


    if re.search(r"lead\s+is\s+qualified|qualified\s+for|is\s+qualified", lowered):
        return "qualify_lead", {}
    if re.search(r"schedule.+quotation", lowered): return "schedule_quotation", {}
    if re.search(r"schedule.+demo", lowered): return "schedule_demo", {}
    if re.search(r"schedule.+meeting", lowered): return "schedule_meeting", {}
    if re.search(r"reassign", lowered): return "reassign_task", {}
    if re.search(r"remind me|set reminder", lowered): return "reminder", {}
    if re.search(r"feedback for", lowered) or re.search(r"meeting done", lowered): return "feedback", {}
    if re.search(r"lead qualified", lowered) or re.search(r"is qualified", lowered): return "qualify_lead", {}

    if re.search(r"new lead|there is a lead|add lead", lowered) or ("lead" in lowered and "tell" in lowered):
        return "new_lead", {}

    if message.count(",") >= 3:  # Detect comma-based structured lead message
        return "new_lead", {}

    return "unknown", {}
