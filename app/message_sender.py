# app/message_sender.py
import os
import requests
import time
from dotenv import load_dotenv

load_dotenv()

MAYT_API_URL = os.getenv("MAYT_API_URL")
MAYT_API_TOKEN = os.getenv("MAYT_API_TOKEN", "1fec7901-7cf7-4bf7-82d9-753299c45ce3")  # fallback if .env missing
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds

def format_phone(phone: str) -> str:
    phone = phone.strip().replace("+", "")
    if not phone.startswith("91"):
        return "91" + phone
    return phone

def send_whatsapp_message(reply_url: str, number: str, message: str) -> bool:
    number = format_phone(number)
    print(f"📤 Sending WhatsApp message to {number}: {message}  TOKEN={MAYT_API_TOKEN}")

    if not reply_url:
        print("❌ Cannot send WhatsApp message, reply_url is missing.")
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
            response = requests.post(reply_url, json=payload, headers=headers, timeout=10)
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
