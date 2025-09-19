# message_sender.py
import os
from typing import Union
import requests
import time
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

load_dotenv()

WHATSIFY_API_URL = os.getenv("WHATSIFY_API_URL")
WHATSIFY_API_KEY = os.getenv("WHATSIFY_API_KEY") # This is your WhatsFlySecret
WHATSIFY_ACCOUNT_ID = os.getenv("WHATSIFY_ACCOUNT_ID") # This is your WhatsFlyAccount

MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds

def format_phone(phone: Union[str, int]) -> str:
    """
    Formats a phone number to include a leading '+' and country code '91' if missing.
    Removes spaces, hyphens, and parentheses for consistent formatting.
    """
    phone_str = str(phone).strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    
    if phone_str.startswith('+'):
        return phone_str
    elif phone_str.startswith('91') and not phone_str.startswith('+91'):
        return '+' + phone_str
    else:
        return '+91' + phone_str

def app_reply_json(message: str, source: str) -> dict:
    """
    Generates a specific JSON response for messages originating from an 'app' source.
    This function is used when the message is not meant for external sending but
    for internal application handling.
    """
    if source.strip().lower() == "app":
        logger.info("✅ Using app-specific message sending logic for source 'app'")
        data = {"status": "success", "reply": message}
        return data
    logger.warning(f"❗ 'app_reply_json' called with non-'app' source: '{source}'. Returning error.")
    return {"status": "error", "reply": "Invalid source for app response"}

def send_message(number: str, message: str, source: str = "whatsapp") -> dict:
    """
    Routes message sending based on the specified source.
    If the source is 'app', it uses the app-specific reply logic.
    Otherwise (e.g., 'whatsapp'), it attempts to send a WhatsApp message via Whatsify.
    """
    if source.strip().lower() == "app":
        return app_reply_json(message, source)
    else:
        logger.info(f"Attempting to send message via WhatsApp for source: '{source}'")
        success = send_whatsapp_message(number, message) 
        if success:
            logger.info(f"Successfully sent WhatsApp message to {number}.")
            return {"status": "success", "sent": True, "reply": message}
        else:
            logger.error(f"Failed to send WhatsApp message to {number}.")
            return {"status": "error", "sent": False, "reply": "Failed to send message"}


def send_whatsapp_message(number: str, message: str) -> bool:
    """
    Sends a WhatsApp message using the Whatsify API,
    conforming to the multipart/form-data requirements.
    """
    formatted_number = format_phone(number)
    logger.info(f"📤 Attempting to send WhatsApp message to {formatted_number}: '{message}' via Whatsify")

    # The documentation indicates the base URL is "https://api.whatsify.me"
    # and endpoints are "/send/whatsapp" or "/api/send/whatsapp".
    # Your logs show "https://api.whatsify.me/api/send/whatsapp".
    # We will stick to the one shown in your logs as it seems to be what you're using.
    target_url = WHATSIFY_API_URL

    if not target_url:
        logger.error("❌ Cannot send WhatsApp message: WHATSIFY_API_URL is not set. Please check your .env file.")
        return False
    if not WHATSIFY_API_KEY:
        logger.error("❌ Cannot send WhatsApp message: WHATSIFY_API_KEY (WhatsFly Secret) is not set. Please check your .env file.")
        return False
    if not WHATSIFY_ACCOUNT_ID:
        logger.error("❌ Cannot send WhatsApp message: WHATSIFY_ACCOUNT_ID (WhatsFly Account ID) is not set. Please check your .env file.")
        return False

    logger.debug(f"Whatsify API URL being used: '{target_url}'")
    logger.debug(f"Whatsify API Key (from .env - FULL VALUE): '{WHATSIFY_API_KEY}'")
    logger.debug(f"Whatsify Account ID (from .env - FULL VALUE): '{WHATSIFY_ACCOUNT_ID}'")

    # Construct the payload as multipart/form-data
    # The 'data' parameter in requests library handles 'multipart/form-data'
    # automatically when it's a dictionary of strings.
    # No need to manually set Content-Type header when using 'data'.
    payload_data = {
        "secret": WHATSIFY_API_KEY,      # As per documentation, 'secret' in form data
        "account": WHATSIFY_ACCOUNT_ID,  # As per documentation, 'account' in form data
        "recipient": formatted_number,   # As per documentation, 'recipient' in form data
        "message": message,              # As per documentation, 'message' in form data
        "type": "text",                  # Default to 'text' as per documentation example
    }

    logger.debug(f"Whatsify API Request Payload (form data): {payload_data}")
    # Note: No custom headers for authentication are needed as per the documentation.
    # The 'secret' and 'account' are part of the form data.

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # Use 'data' parameter for form-encoded requests.
            # requests will automatically set Content-Type: multipart/form-data
            response = requests.post(target_url, data=payload_data, timeout=10)
            logger.info(f"📤 Attempt {attempt} to Whatsify: Status Code {response.status_code} - Response: {response.text}")

            if response.status_code == 200 or response.status_code == 202:
                logger.info(f"✅ Successfully sent or accepted WhatsApp message to {formatted_number}.")
                return True
            elif response.status_code == 400:
                # 400 Bad Request can indicate issues with the payload,
                # including missing required fields if the API key itself was validated
                # but the request structure was wrong.
                logger.error(f"❌ Bad Request (400) from Whatsify API on attempt {attempt}: "
                             f"Please check payload structure and field values. Response: {response.text}")
                break
            elif response.status_code == 403:
                # 403 Forbidden, as per docs, could mean "This API Key does not have this privilege"
                # If we're still getting "API key is required" here, it means the 'secret'
                # in the form data itself is still invalid or not recognized for the operation.
                logger.error(f"❌ Authentication/Permission (403 Forbidden) error from Whatsify API on attempt {attempt}: "
                             f"The API key provided in the form data might be incorrect, expired, or lack 'wa_send' permission. "
                             f"Response: {response.text}. "
                             f"**Action required**: Please carefully verify the values of WHATSIFY_API_KEY and WHATSIFY_ACCOUNT_ID "
                             f"in your .env file and ensure the API key has the 'wa_send' privilege on Whatsify dashboard.")
                break
            elif 500 <= response.status_code < 600:
                logger.warning(f"⚠️ Server error (5xx) from Whatsify API on attempt {attempt}, retrying after {RETRY_DELAY}s...")
            else:
                logger.error(f"❌ Non-retryable client error ({response.status_code}) from Whatsify API: "
                             f"Response: {response.text}. Stopping retries for this type of error.")
                break
        except requests.Timeout:
            logger.warning(f"⏰ Timeout connecting to Whatsify API on attempt {attempt}, retrying in {RETRY_DELAY}s...")
        except requests.ConnectionError as e:
            logger.warning(f"🔌 Connection error to Whatsify API on attempt {attempt}: {e}. Retrying in {RETRY_DELAY}s...")
        except requests.RequestException as e:
            logger.error(f"❌ General RequestException connecting to Whatsify API on attempt {attempt}: {e}. Stopping retries.")
            break

        time.sleep(RETRY_DELAY)

    logger.error("🚫 All attempts to send WhatsApp message via Whatsify failed.")
    return False