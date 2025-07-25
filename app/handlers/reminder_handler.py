# app/handlers/reminder_handler.py
from sqlalchemy.orm import Session
from app.models import Reminder, Lead, User
from app.message_sender import send_message
from app.crud import get_lead_by_company, get_user_by_phone
from datetime import datetime, timedelta
import re
import dateparser
import logging

logger = logging.getLogger(__name__)

def parse_reminder_details(text: str) -> tuple[str | None, str | None, str | None]:
    """
    Parses a reminder message using a single, more robust regex.
    Handles formats like: "remind me to [message] for/with [company] on/at [time]"
    """
    # Using named groups for clarity: ?P<name>
    pattern = re.compile(
        r"remind me to\s+(?P<message>.+?)\s+(?:for|with)\s+(?P<company>.+?)\s+(?:at|on)\s+(?P<time>.+)",
        re.IGNORECASE
    )
    match = pattern.search(text)
    if match:
        data = match.groupdict()
        return data.get("message").strip(), data.get("company").strip(), data.get("time").strip()
    return None, None, None


async def handle_set_reminder(db: Session, message: str, sender: str, reply_url: str, source: str = "whatsapp"):
    """
    Handles setting a reminder for a user about a lead.
    """
    try:
        reminder_msg, lead_name, time_str = parse_reminder_details(message)

        if not all([reminder_msg, lead_name, time_str]):
            error_msg = "⚠️ Invalid format. Use: `Remind me to [action] for [Company] on [Date/Time]`"
            return send_message(reply_url, sender, error_msg, source)

        # Use the powerful dateparser library
        remind_time = dateparser.parse(time_str, settings={'PREFER_DATES_FROM': 'future'})
        if not remind_time:
            error_msg = f"❌ I couldn't understand the date or time: '{time_str}'. Please be more specific."
            return send_message(reply_url, sender, error_msg, source)

        # Fetch Lead and User
        lead = get_lead_by_company(db, lead_name)
        if not lead:
            return send_message(reply_url, sender, f"⚠️ Could not find lead: {lead_name}", source)
        
        # Correctly find user by their phone number (sender)
        user = get_user_by_phone(db, sender)
        if not user:
            return send_message(reply_url, sender, "⚠️ You are not recognized in the system. Cannot set reminder.", source)

        # Create reminder with a consistent structure
        reminder = Reminder(
            lead_id=lead.id,
            user_id=user.id,
            assigned_to=user.id,  # The reminder is assigned to the person who set it
            remind_time=remind_time,
            message=reminder_msg,
            status="pending" # Use a status for better tracking
        )
        db.add(reminder)
        db.commit()

        success_msg = f"✅ Reminder set for *{lead.company_name}* on {remind_time.strftime('%A, %b %d at %I:%M %p')}."
        return send_message(reply_url, sender, success_msg, source)

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error setting reminder: {e}", exc_info=True)
        return send_message(reply_url, sender, "❌ An internal error occurred while setting the reminder.", source)