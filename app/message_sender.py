# app/message_sender.py
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

# It is highly recommended to set this in your .env file
# For example: BASE_URL=https://your-ngrok-or-domain.com
BASE_URL = os.getenv("BASE_URL", "http://157.20.215.187:7200") # Replace default with your ngrok url if it changes

MAX_RETRIES = 3
RETRY_DELAY = 5  

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
    Sends a WhatsApp TEXT message using the Whatsify API,
    conforming to the multipart/form-data requirements.
    """
    formatted_number = format_phone(number)
    logger.info(f"📤 Attempting to send WhatsApp TEXT message to {formatted_number}: '{message}' via Whatsify")

    target_url = WHATSIFY_API_URL

    if not all([target_url, WHATSIFY_API_KEY, WHATSIFY_ACCOUNT_ID]):
        logger.error("❌ Cannot send WhatsApp message: Whatsify API credentials or URL are not set in .env file.")
        return False

    logger.debug(f"Whatsify API URL being used: '{target_url}'")
    logger.debug(f"Whatsify API Key (from .env): '{WHATSIFY_API_KEY}'")
    logger.debug(f"Whatsify Account ID (from .env): '{WHATSIFY_ACCOUNT_ID}'")

    payload_data = {
        "secret": WHATSIFY_API_KEY,
        "account": WHATSIFY_ACCOUNT_ID,
        "recipient": formatted_number,
        "message": message,
        "type": "text",
    }

    logger.debug(f"Whatsify API Request Payload (form data): {payload_data}")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(target_url, data=payload_data, timeout=10)
            logger.info(f"📤 Attempt {attempt} to Whatsify: Status Code {response.status_code} - Response: {response.text}")

            if 200 <= response.status_code < 300:
                logger.info(f"✅ Successfully sent or accepted WhatsApp TEXT message to {formatted_number}.")
                return True
            else:
                logger.error(f"❌ Error from Whatsify API on attempt {attempt}: {response.text}")
                if response.status_code < 500: # Don't retry client errors (4xx)
                    break
        except requests.RequestException as e:
            logger.error(f"❌ RequestException on attempt {attempt}: {e}")

        time.sleep(RETRY_DELAY)

    logger.error("🚫 All attempts to send WhatsApp TEXT message failed.")
    return False

def send_whatsapp_message_with_media(number: str, file_path: str, caption: str, message_type: str) -> bool:
    """
    Sends a WhatsApp message with a media or document attachment.
    """
    formatted_number = format_phone(number)
    
    if not file_path:
        logger.error("Cannot send media message: file_path is missing.")
        return False

    target_url = WHATSIFY_API_URL

    if not all([target_url, WHATSIFY_API_KEY, WHATSIFY_ACCOUNT_ID, BASE_URL]):
        logger.error("❌ Cannot send WhatsApp media: Whatsify credentials, URL, or BASE_URL are not set in .env file.")
        return False

    document_extensions = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv', '.txt', '.ppt', '.pptx']
    _, file_extension = os.path.splitext(file_path.lower())

    correct_message_type = "document" if file_extension in document_extensions else "media"
    
    logger.info(f"📤 Attempting to send WhatsApp {correct_message_type.upper()} to {formatted_number} via Whatsify (Original type was '{message_type}')")
    
    # --- START OF THE CRITICAL FIX ---
    # The problem was here. We must extract ONLY the filename from the full local path.
    # For example, from 'D:\\Indus_CRM\\...\\report.pdf', we need just 'report.pdf'.
    file_name = os.path.basename(file_path)
    public_file_url = f"{BASE_URL.rstrip('/')}/web/attachments/preview/{file_name}"
    # --- END OF THE CRITICAL FIX ---

    logger.info(f"Using public file URL for WhatsApp: {public_file_url}")

    # Base payload required for all media/document types
    payload_data = {
        "secret": WHATSIFY_API_KEY,
        "account": WHATSIFY_ACCOUNT_ID,
        "recipient": formatted_number,
        "caption": caption,
        "type": correct_message_type,
        "message": caption # API requires this field even for media/docs
    }

    # Add parameters specific to the message type
    if correct_message_type == 'document':
        payload_data['document_url'] = public_file_url
        payload_data['document_name'] = file_name
    else:
        payload_data['media_url'] = public_file_url
    
    logger.debug(f"Whatsify API Request Payload (form data): {payload_data}")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(target_url, data=payload_data, timeout=20)
            logger.info(f"📤 Attempt {attempt} to Whatsify ({correct_message_type.upper()}): Status {response.status_code} - Response: {response.text}")

            if 200 <= response.status_code < 300:
                logger.info(f"✅ Successfully sent or accepted WhatsApp {correct_message_type.upper()} to {formatted_number}.")
                return True
            else:
                logger.error(f"❌ Error from Whatsify API on attempt {attempt}: {response.text}")
                if response.status_code < 500:
                    break
        except requests.RequestException as e:
            logger.error(f"❌ RequestException on attempt {attempt}: {e}")

        time.sleep(RETRY_DELAY)
    
    logger.error(f"🚫 All attempts to send WhatsApp {correct_message_type.upper()} message failed.")
    return False  