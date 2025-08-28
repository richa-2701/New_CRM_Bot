# message_sender.py
import os
from typing import Union
import requests
import time
from dotenv import load_dotenv

load_dotenv()

MAYT_API_URL = os.getenv("MAYT_API_URL")
MAYT_API_TOKEN = os.getenv("MAYT_API_TOKEN", "eabf6096-5968-4b07-a74a-d10e34ffd97e")  # fallback if .env missing
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds

def format_phone(phone: Union[str, int]) -> str:
    """
    Safely formats a phone number, whether it's passed as a string or an integer.
    """
    # 1. Convert the input to a string, no matter what it is.
    phone_str = str(phone)
    
    # 2. Perform string operations on the guaranteed string.
    phone_str = phone_str.strip().replace("+", "")
    
    if not phone_str.startswith("91"):
        return "91" + phone_str
    return phone_str

def app_reply_json(message: str, source: str) -> dict:
    """Returns JSON response for app-based messages"""
    if source.strip().lower() == "app":
        print("✅ Using app-specific message sending logic")
        data = {"status": "success", "reply": message}
        return data
    return {"status": "error", "reply": "Invalid source for app response"}

def send_message(reply_url: str, number: str, message: str, source: str = "whatsapp") -> dict:
    """
    Unified message sending function that handles both WhatsApp and app sources
    Returns dict for both app and WhatsApp for consistency
    """
    if source.strip().lower() == "app":
        return app_reply_json(message, source)
    else:
        # WhatsApp logic
        success = send_whatsapp_message(reply_url, number, message)
        return {"status": "success" if success else "error", "sent": success, "reply": message if success else "Failed to send message"}


def send_whatsapp_message(reply_url: str, number: str, message: str,) -> bool:
    """
    Sends a WhatsApp message.
    Uses the provided `reply_url` if available (for replying to an incoming message).
    Falls back to the global `MAYT_API_URL` for sending new, proactive messages.
    """
    number = format_phone(number)
    print(f"📤 Sending WhatsApp message to {number}: {message}  TOKEN={MAYT_API_TOKEN}")

    # --- NEW: Use reply_url if provided, otherwise fall back to the global API URL ---
    target_url = reply_url or MAYT_API_URL

    if not target_url:
        print("❌ Cannot send WhatsApp message: reply_url is missing and MAYT_API_URL is not configured in .env")
        return False

    payload = {
        "to_number": number,
        "type": "text",
        "message": message
    }
    headers = {
        "x-maytapi-key": MAYT_API_TOKEN,
        "Content-Type": "application/json"
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # Use the determined target_url
            response = requests.post(target_url, json=payload, headers=headers, timeout=10)
            print(f"📤 Attempt {attempt}: {response.status_code} - {response.text}")

            if response.status_code == 200:
                return True  # ✅ Successfully sent
            elif 500 <= response.status_code < 600:
                print(f"⚠️ Server error on attempt {attempt}, retrying after {RETRY_DELAY}s...")
            else:
                print(f"❌ Non-retryable error: {response.status_code}")
                break
        except requests.Timeout:
            print(f"⏰ Timeout on attempt {attempt}, retrying in {RETRY_DELAY}s...")
        except requests.RequestException as e:
            print(f"❌ RequestException on attempt {attempt}: {str(e)}")

        time.sleep(RETRY_DELAY)

    print("🚫 All attempts to send WhatsApp message failed.")
    return False
