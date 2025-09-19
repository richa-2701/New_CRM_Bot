import re
from sqlalchemy.orm import Session
from app.models import Reminder, Lead, User
from app.message_sender import send_message # Ensure send_whatsapp_message is NOT directly imported here if only send_message is intended for replies
from app.crud import get_lead_by_company, get_user_by_phone, create_activity_log, create_reminder
from app.schemas import ActivityLogCreate, ReminderCreate
from datetime import datetime, timedelta, date, time
import re
import dateparser
import logging

logger = logging.getLogger(__name__)

# --- THIS IS THE NEW, MORE ROBUST PARSER ---
def parse_reminder_details(text: str) -> tuple[str | None, str | None, str | None]:
    """
    Intelligently parses a reminder string by finding the last occurrence of 'for' or 'with'
    as the separator for the company name.
    """
    text_lower = text.lower()
    
    # Find the index of the last " for " or " with "
    last_for_index = text_lower.rfind(" for ")
    last_with_index = text_lower.rfind(" with ")
    
    separator_index = max(last_for_index, last_with_index)

    if separator_index == -1:
        # If no separator is found, the format is invalid for a reminder
        return None, None, None

    # The company name is everything after the last separator
    company_name = text[separator_index + 5:].strip() # +5 accounts for " for " or " with "
    
    # The message and time is everything before the separator
    message_and_time = text[:separator_index].replace("Remind me to", "").strip()

    # Now, find the time string within that first part using dateparser's more powerful search
    # This can find phrases like "tomorrow at 2pm" or "next Friday"
    found_dates = dateparser.search.search_dates(message_and_time, settings={'PREFER_DATES_FROM': 'future'})
    
    reminder_msg = message_and_time
    time_str = None

    if found_dates:
        # We found a time expression
        date_string_found, date_obj = found_dates[0]
        time_str = date_string_found
        
        # Clean up the message by removing the time part
        # This is a simple replacement, works for most cases
        reminder_msg = message_and_time.replace(date_string_found, "").strip()

    return reminder_msg, company_name, time_str
# --- END OF NEW PARSER ---


async def handle_set_reminder(db: Session, message: str, sender: str, reply_url: str, source: str = "whatsapp"):
    """
    Handles setting a reminder. If no time is provided, defaults to the next day at 12 PM.
    Also handles logging a simple activity if the format matches.
    """
    try:
        # First, try to parse it as a "log activity" command, which has a simpler structure
        log_pattern = re.compile(r"add activity for\s+(?P<company>.+?),\s*(?P<details>.+)", re.IGNORECASE)
        log_match = log_pattern.search(message)
        if log_match:
            lead = get_lead_by_company(db, log_match.group('company').strip())
            if not lead:
                # Corrected: send_message arguments
                return send_message(number=sender, message=f"⚠️ Could not find lead: {log_match.group('company').strip()}", source=source)
            
            user = get_user_by_phone(db, sender)
            log_details = f"{log_match.group('details').strip()} - Logged by {user.username if user else sender}"
            
            create_activity_log(db, ActivityLogCreate(lead_id=lead.id, phase=lead.status, details=log_details,activity_type="Call"))
            
            # Corrected: send_message arguments
            return send_message(number=sender, message=f"✅ Activity logged for *{lead.company_name}*.", source=source)

        # If not a log, try to parse it as a reminder using our new robust parser
        reminder_msg, lead_name, time_str = parse_reminder_details(message)

        if not reminder_msg or not lead_name:
            error_msg = "⚠️ Invalid format. Use: `Remind me to [action] for [Company] on [Date/Time]` or `Add activity for [Company], [details]`"
            # Corrected: send_message arguments
            return send_message(number=sender, message=error_msg, source=source)

        remind_time = None
        default_scheduled = False

        if time_str:
            remind_time = dateparser.parse(time_str, settings={'PREFER_DATES_FROM': 'future'})
            if not remind_time:
                error_msg = f"❌ I couldn't understand the date or time: '{time_str}'. Please be more specific."
                # Corrected: send_message arguments
                return send_message(number=sender, message=error_msg, source=source)
        else:
            # If no time_str was found, set reminder for next day at 12:00 PM
            today = date.today()
            tomorrow = today + timedelta(days=1)
            remind_time = datetime.combine(tomorrow, time(12, 0)) # 12:00 PM
            default_scheduled = True

        lead = get_lead_by_company(db, lead_name)
        if not lead:
            # Corrected: send_message arguments
            return send_message(number=sender, message=f"⚠️ Could not find lead: '{lead_name}'", source=source)
        
        user = get_user_by_phone(db, sender)
        if not user:
            # Corrected: send_message arguments
            return send_message(number=sender, message="⚠️ You are not recognized in the system. Cannot set reminder.", source=source)

        # Using create_reminder for consistency
        create_reminder(db, ReminderCreate(
            lead_id=lead.id,
            user_id=user.id,
            assigned_to=user.username,
            remind_time=remind_time,
            message=reminder_msg,
            activity_type="Follow-up",
            is_hidden_from_activity_log=False, # User-generated reminder, should be visible
            status="pending"
        ))

        time_format = '%d/%m/%Y %I:%M %p'
        success_msg = f"✅ Reminder set for *{lead.company_name}* on {remind_time.strftime(time_format)}."
        if default_scheduled:
            success_msg += " (Default time used as none was provided)."
            
        # Corrected: send_message arguments
        return send_message(number=sender, message=success_msg, source=source)

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error setting reminder: {e}", exc_info=True)
        # Corrected: send_message arguments
        return send_message(number=sender, message="❌ An internal error occurred while setting the reminder.", source=source)