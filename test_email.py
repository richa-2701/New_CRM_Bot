# test_email.py
import os
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv

# Load environment variables from your .env file
load_dotenv()

# --- Load settings ---
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_SENDER_EMAIL = os.getenv("SMTP_SENDER_EMAIL")

# --- IMPORTANT: Put your OWN email address here to receive the test ---
RECIPIENT_EMAIL = "your-personal-email@example.com"

print("--- Testing Email Configuration ---")
print(f"Server: {SMTP_SERVER}")
print(f"Port: {SMTP_PORT}")
print(f"Username: {SMTP_USERNAME}")
print(f"Password Loaded: {'Yes' if SMTP_PASSWORD else 'No'}")
print(f"Sender Email: {SMTP_SENDER_EMAIL}")
print("---------------------------------")

if not all([SMTP_SERVER, SMTP_USERNAME, SMTP_PASSWORD, SMTP_SENDER_EMAIL]):
    print("❌ Error: One or more SMTP environment variables are missing in your .env file.")
else:
    try:
        msg = MIMEText("This is a test email from the CRM application.")
        msg['Subject'] = 'CRM Email Test'
        msg['From'] = SMTP_SENDER_EMAIL
        msg['To'] = RECIPIENT_EMAIL

        print(f"\nAttempting to connect to {SMTP_SERVER}:{SMTP_PORT}...")
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.set_debuglevel(1) # This will print the full connection log
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_SENDER_EMAIL, [RECIPIENT_EMAIL], msg.as_string())
        print("\n✅✅✅ SUCCESS: Test email sent successfully! Your .env settings are correct.")

    except smtplib.SMTPAuthenticationError:
        print("\n❌❌❌ FAILURE: SMTP Authentication Failed.")
        print("     This almost always means your SMTP_USERNAME or SMTP_PASSWORD is incorrect.")
        print("     If using Gmail, did you generate and use an 'App Password'?")
    except Exception as e:
        print(f"\n❌❌❌ FAILURE: An unexpected error occurred: {e}")