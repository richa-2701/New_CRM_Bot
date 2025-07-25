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
- "phone_2"
- "turnover"
- "current_system"
- "machine_specification"
- "challenges"

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


# --- THIS FUNCTION IS NOW CORRECTED ---
def parse_update_fields(message: str):
    """
    Uses GPT to extract only optional lead fields from a message for updating an existing lead.
    """
    prompt = f"""
You are an expert CRM assistant. Extract ONLY the following optional fields from the user's message for updating an existing lead.

The message can be in natural language (e.g., "Address is Indore, team size is 10") or a simple comma-separated list.

👉 **NEW RULE for comma-separated values without labels:**
If the user provides a list of values separated by commas, map them to the following fields IN THIS EXACT ORDER. The user may not provide all values.
1. `segment`
2. `team_size`
3. `phone_2`
4. `turnover`
5. `current_system`
6. `machine_specification`
7. `challenges`

Example Input: "Retail, 50, 7788667766, 4 cr, Xyz, 4 colour, estimation delay"
Example Output: 
{{
  "segment": "Retail",
  "team_size": "50",
  "phone_2": "7788667766",
  "turnover": "4 cr",
  "current_system": "Xyz",
  "machine_specification": "4 colour",
  "challenges": "estimation delay"
}}

Optional Fields to extract:
- "email"
- "address"
- "team_size"
- "segment"
- "remark"
- "phone_2"
- "turnover"
- "current_system"
- "machine_specification"
- "challenges"

Do NOT return core fields like company_name, contact_name, or phone.
If a field is not present, omit it from the JSON.
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
        logger.info(f"🔍 Raw GPT Response for optional fields: {result_content}")

        try:
            data = json.loads(result_content)
        except json.JSONDecodeError:
            logger.error("❌ GPT returned invalid JSON")
            return {}, "❌ GPT returned invalid JSON"

        optional = [
            "email", "address", "team_size", "segment", "remark", "phone_2", 
            "turnover", "current_system", "machine_specification", "challenges"
        ]
        update_data = {k: v for k, v in data.items() if k in optional and v}

        return update_data, "✅ Lead update fields parsed successfully."

    except requests.exceptions.RequestException as e:
        logger.error(f"❌ GPT API request error: {e}")
        return {}, "❌ Could not connect to the AI service."
    except Exception as e:
        logger.error(f"❌ GPT processing error: {e}")
        return {}, "❌ An unexpected error occurred."


# --- NEW PARSER FUNCTION ---
def parse_core_lead_update(message: str):
    """
    Uses GPT to extract core lead fields for an update, such as company_name.
    """
    prompt = f"""
You are an expert CRM assistant. The user wants to update core details of an existing lead.
Extract any of the following fields if they are present in the message.

Fields to extract for update:
- "company_name"
- "contact_name"
- "phone"
- "email"
- "address"
- "phone_2"

The user might provide the information in key-value pairs or natural language.
For example: "The company name is now XYZ Corp, contact person is now Sunita."
Another example: "company: XYZ Corp, phone: 9988776655"

If a field is not mentioned, omit it from the JSON output.
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
        logger.info(f"🔍 Raw GPT Response for core update: {result_content}")
        
        data = json.loads(result_content)
        
        # Filter to ensure only valid fields are returned
        core_fields = ["company_name", "contact_name", "phone", "email", "address", "phone_2"]
        update_data = {k: v for k, v in data.items() if k in core_fields and v}
        
        return update_data, "✅ Core lead update fields parsed."

    except Exception as e:
        logger.error(f"❌ GPT core update processing error: {e}", exc_info=True)
        return {}, "❌ An unexpected error occurred during core update parsing."


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

    if re.search(r"meeting (is )?done", lowered):
        # Make "meeting done" more specific to avoid conflict with feedback
        return "meeting_done", {}

    if re.search(r"lead\s+is\s+qualified|qualified\s+for|is\s+qualified|lead qualified", lowered):
        return "qualify_lead", {}

    if re.search(r"schedule.+quotation", lowered): return "schedule_quotation", {}
    if re.search(r"schedule.+demo", lowered): return "schedule_demo", {}
    if re.search(r"schedule.+meeting|meeting.+schedule", lowered): return "schedule_meeting", {}
    if re.search(r"reassign", lowered): return "reassign_task", {}
    if re.search(r"remind me|set reminder", lowered): return "reminder", {}
    if re.search(r"feedback for", lowered): return "feedback", {}

    if re.search(r"new lead|there is a lead|add lead", lowered) or ("lead" in lowered and "tell" in lowered):
        return "new_lead", {}

    if message.count(",") >= 3:
        return "new_lead", {}

    if re.search(r"demo (is )?done|demo completed|demo finished|demo ho gya|demo ho gaya", lowered):
        return "demo_done", {}

    return "unknown", {}