# gpt_parser.py
import os
import requests
import json
import re
import logging
from dotenv import load_dotenv
import dateparser
from datetime import datetime, timedelta

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
You are an expert CRM assistant. Your primary task is to extract structured information from a user's message.
A critical rule is that the "company_name" can contain multiple words and spaces (e.g., "The Park Hotels", "ABC Corp Pvt Ltd"). You must capture the full company name.

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
    Extracts the company name from various message formats by checking patterns.
    - "Lead for [Company Name] is not qualified"
    - "Qualified for [Company Name]"
    - "[Company Name] is not our segment"
    - "[Company Name]"
    """
    msg = message.strip()
    lowered_msg = msg.lower()

    # Pattern 1: Catches "for [Company Name] is ...". Non-greedy.
    match = re.search(r"for\s+(.*?)\s+is", lowered_msg)
    if match:
        company_name = match.group(1).strip()
        if company_name:
            return company_name.title()

    # Pattern 2: Catches "... for [Company Name]" where the name is at the end.
    match = re.search(r"for\s+(.+)", lowered_msg)
    if match:
        company_name = match.group(1).strip()
        if company_name:
            return company_name.title()

    # Pattern 3: Catches "[Company Name] is not qualified", etc.
    status_keywords = [
        "is not qualified", "not qualified", "is qualified", "qualified",
        "is not our segment", "not our segment"
    ]
    for keyword in status_keywords:
        # We check if the message ENDS with the keyword to be more specific
        if lowered_msg.endswith(keyword):
            company_name = lowered_msg[:-len(keyword)].strip()
            if company_name:
                return company_name.title()

    # Fallback for when the user just provides the company name
    keywords_to_avoid = [
        "lead", "qualified", "demo", "meeting", "update", "schedule", "new",
        "reminder", "done", "not", "our", "segment", "is", "for"
    ]
    words_in_message = lowered_msg.split()
    if 1 <= len(words_in_message) <= 5 and not any(word in words_in_message for word in keywords_to_avoid):
        return msg.title()

    return ""

def parse_intent_and_fields(message: str):
    """
    Detects user's intent using fast regex-based rules.
    """
    lowered = message.lower()

    # --- NEW: Added intent for generating a report ---
    if re.search(r"give report of|generate report for|report of", lowered):
        return "generate_report", {}

    if re.search(r"meeting (is )?done", lowered):
        # Make "meeting done" more specific to avoid conflict with feedback
        return "meeting_done", {}
    
    if re.search(r"lead\s+(for|is)\s+.+?\s+is\s+not\s+qualified|not\s+qualified", lowered):
        return "unqualify_lead", {}

    if re.search(r"not\s+(in|our)\s+our\s+segment|not\s+our\s+segment", lowered):
        return "not_our_segment", {}

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

# --- NEW: Function to parse the report request details ---
def parse_report_request(message: str):
    """
    Parses a report request to extract username, start date, and end date.
    Example: "Give report of Banwari from 01/09/25 to 25/09/25"
    """
    # Regex to capture the three key parts: username, start date, end date
    match = re.search(r'of\s+(.+?)\s+from\s+([\d/.-]+)\s+to\s+([\d/.-]+)', message, re.IGNORECASE)
    
    if not match:
        return None, None, None

    username = match.group(1).strip()
    start_date_str = match.group(2).strip()
    end_date_str = match.group(3).strip()

    try:
        # Use dateparser for robust date conversion
        start_date = dateparser.parse(start_date_str, settings={'DATE_ORDER': 'DMY'}).date()
        end_date = dateparser.parse(end_date_str, settings={'DATE_ORDER': 'DMY'}).date()
        return username, start_date, end_date
    except Exception:
        # If dates are invalid
        return None, None, None


def parse_datetime_from_text(text: str) -> datetime:
    """
    Parses a natural language string to find a date and time.
    This version first tries to extract a specific date/time phrase from the text
    before passing it to the dateparser library for robust parsing.
    """
    
    # --- STEP 1: Use regex to find and isolate the date/time part of the string ---
    # This pattern looks for phrases like "on [date] at [time]", "tomorrow at 5pm", etc.
    # It helps remove confusing words like "follow up".
    match = re.search(r'(on\s|at\s|tomorrow|today|next\sweek)[\w\s:/]+', text, re.IGNORECASE)
    
    datetime_string_to_parse = text # Default to the full string
    if match:
        # If we found a specific phrase, use that for parsing.
        datetime_string_to_parse = match.group(0)
        logger.info(f"🔍 Extracted datetime phrase: '{datetime_string_to_parse}'")

    # --- STEP 2: Configure and run the dateparser ---
    settings = {
        'DATE_ORDER': 'DMY',
        'PREFER_DATES_FROM': 'future',
        'RELATIVE_BASE': datetime.now()
    }
    
    parsed_date = dateparser.parse(datetime_string_to_parse, settings=settings)

    if parsed_date:
        logger.info(f"📅 Parsed '{datetime_string_to_parse}' into datetime: {parsed_date}")
        return parsed_date
    else:
        logger.warning(f"⚠️ Could not parse datetime from '{text}'. Defaulting to tomorrow at 12 PM.")
        tomorrow = datetime.now() + timedelta(days=1)
        return tomorrow.replace(hour=12, minute=0, second=0, microsecond=0)