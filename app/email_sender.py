# app/email_sender.py
import os
import smtplib
import logging
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# --- Load SMTP settings from environment variables ---
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_SENDER_EMAIL = os.getenv("SMTP_SENDER_EMAIL")

def send_email_with_attachment(
    recipients: List[str],
    subject: str,
    body: str,
    attachment_path: str,
    attachment_filename: str
) -> bool:
    """
    Sends an email with a single PDF attachment to a list of recipients.
    (This function is kept for any other part of the app that might use it).
    """
    if not all([SMTP_SERVER, SMTP_USERNAME, SMTP_PASSWORD, SMTP_SENDER_EMAIL]):
        logger.error("❌ SMTP environment variables are not fully configured. Email not sent.")
        return False

    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From'] = SMTP_SENDER_EMAIL
    msg['To'] = ", ".join(recipients)

    msg.attach(MIMEText(body, 'plain'))

    try:
        with open(attachment_path, "rb") as f:
            part = MIMEApplication(f.read(), Name=attachment_filename)
        part['Content-Disposition'] = f'attachment; filename="{attachment_filename}"'
        msg.attach(part)
    except FileNotFoundError:
        logger.error(f"❌ Attachment file not found at path: {attachment_path}. Email not sent.")
        return False
    except Exception as e:
        logger.error(f"❌ Failed to read or attach the file: {e}", exc_info=True)
        return False

    try:
        logger.info(f"Connecting to SMTP server: {SMTP_SERVER}:{SMTP_PORT}")
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_SENDER_EMAIL, recipients, msg.as_string())
            logger.info(f"✅ Successfully sent email to: {', '.join(recipients)}")
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error("❌ SMTP Authentication Failed. Check username/password.")
        return False
    except Exception as e:
        logger.error(f"❌ An unexpected error occurred while sending email: {e}", exc_info=True)
        return False

# --- START: NEW FUNCTION FOR MULTIPLE ATTACHMENTS ---
def send_email_with_multiple_attachments(
    recipients: List[str],
    subject: str,
    body: str,
    attachment_paths: List[str]
) -> bool:
    """
    Sends an email with multiple PDF attachments to a list of recipients.
    """
    if not all([SMTP_SERVER, SMTP_USERNAME, SMTP_PASSWORD, SMTP_SENDER_EMAIL]):
        logger.error("❌ SMTP environment variables are not fully configured. Email not sent.")
        return False

    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From'] = SMTP_SENDER_EMAIL
    msg['To'] = ", ".join(recipients)

    msg.attach(MIMEText(body, 'plain'))

    for path in attachment_paths:
        try:
            with open(path, "rb") as f:
                filename = os.path.basename(path)
                part = MIMEApplication(f.read(), Name=filename)
            part['Content-Disposition'] = f'attachment; filename="{filename}"'
            msg.attach(part)
            logger.info(f"   Attached file: {filename}")
        except FileNotFoundError:
            logger.error(f"❌ Attachment file not found at path: {path}. Skipping this attachment.")
            continue
        except Exception as e:
            logger.error(f"❌ Failed to read or attach the file {path}: {e}", exc_info=True)
            return False

    if not msg.get_payload()[1:]:
        logger.warning("No valid attachments could be added. Email will be sent without attachments.")

    try:
        logger.info(f"Connecting to SMTP server: {SMTP_SERVER}:{SMTP_PORT}")
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_SENDER_EMAIL, recipients, msg.as_string())
            logger.info(f"✅ Successfully sent weekly report email to: {', '.join(recipients)}")
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error("❌ SMTP Authentication Failed. Check username/password.")
        return False
    except Exception as e:
        logger.error(f"❌ An unexpected error occurred while sending email: {e}", exc_info=True)
        return False
# --- END: NEW FUNCTION ---