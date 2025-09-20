# reminder_handler.py
import re
from sqlalchemy.orm import Session
from app.models import Reminder, Lead, User
from app.message_sender import send_message
from app.crud import get_lead_by_company, get_user_by_phone, create_activity_log, create_reminder
from app.schemas import ActivityLogCreate, ReminderCreate
from datetime import datetime, timedelta, date, time
import dateparser
import logging
# --- NEW: Import pytz for timezone handling ---
import pytz

logger = logging.getLogger(__name__)

def parse_reminder_details(text: str) -> tuple[str | None, str | None, str | None]:
    text_lower = text.lower()
    last_for_index = text_lower.rfind(" for ")
    last_with_index = text_lower.rfind(" with ")
    separator_index = max(last_for_index, last_with_index)
    if separator_index == -1:
        return None, None, None
    company_name = text[separator_index + 5:].strip()
    message_and_time = text[:separator_index].replace("Remind me to", "").strip()
    found_dates = dateparser.search.search_dates(message_and_time, settings={'PREFER_DATES_FROM': 'future'})
    reminder_msg = message_and_time
    time_str = None
    if found_dates:
        date_string_found, date_obj = found_dates[0]
        time_str = date_string_found
        reminder_msg = message_and_time.replace(date_string_found, "").strip()
    return reminder_msg, company_name, time_str


async def handle_set_reminder(db: Session, message: str, sender: str, reply_url: str, source: str = "whatsapp"):
    """
    Handles setting a reminder. Correctly converts local parsed time to UTC before saving.
    """
    try:
        log_pattern = re.compile(r"add activity for\s+(?P<company>.+?),\s*(?P<details>.+)", re.IGNORECASE)
        log_match = log_pattern.search(message)
        if log_match:
            lead = get_lead_by_company(db, log_match.group('company').strip())
            if not lead:
                return send_message(number=sender, message=f"⚠️ Could not find lead: {log_match.group('company').strip()}", source=source)
            user = get_user_by_phone(db, sender)
            log_details = f"{log_match.group('details').strip()} - Logged by {user.username if user else sender}"
            create_activity_log(db, ActivityLogCreate(lead_id=lead.id, phase=lead.status, details=log_details,activity_type="Call"))
            return send_message(number=sender, message=f"✅ Activity logged for *{lead.company_name}*.", source=source)

        reminder_msg, lead_name, time_str = parse_reminder_details(message)

        if not reminder_msg or not lead_name:
            error_msg = "⚠️ Invalid format. Use: `Remind me to [action] for [Company] on [Date/Time]` or `Add activity for [Company], [details]`"
            return send_message(number=sender, message=error_msg, source=source)

        remind_time_local_naive = None
        default_scheduled = False

        if time_str:
            remind_time_local_naive = dateparser.parse(time_str, settings={'PREFER_DATES_FROM': 'future', 'RELATIVE_BASE': datetime.now()})
            if not remind_time_local_naive:
                error_msg = f"❌ I couldn't understand the date or time: '{time_str}'. Please be more specific."
                return send_message(number=sender, message=error_msg, source=source)
        else:
            today = date.today()
            tomorrow = today + timedelta(days=1)
            remind_time_local_naive = datetime.combine(tomorrow, time(12, 0))
            default_scheduled = True

        lead = get_lead_by_company(db, lead_name)
        if not lead:
            return send_message(number=sender, message=f"⚠️ Could not find lead: '{lead_name}'", source=source)
        
        user = get_user_by_phone(db, sender)
        if not user:
            return send_message(number=sender, message="⚠️ You are not recognized in the system. Cannot set reminder.", source=source)

        # --- THIS IS THE FIX ---
        # Convert the parsed local time to a naive UTC time for database storage
        try:
            local_tz = pytz.timezone('Asia/Kolkata') # Your local timezone
            remind_time_local_aware = local_tz.localize(remind_time_local_naive)
            remind_time_utc_aware = remind_time_local_aware.astimezone(pytz.utc)
            remind_time_utc_naive = remind_time_utc_aware.replace(tzinfo=None)
        except Exception as e:
            logger.error(f"Timezone conversion failed in reminder_handler: {e}. Falling back to naive time.")
            remind_time_utc_naive = remind_time_local_naive

        create_reminder(db, ReminderCreate(
            lead_id=lead.id,
            user_id=user.id,
            assigned_to=user.username,
            remind_time=remind_time_utc_naive, # Use the corrected UTC time
            message=reminder_msg,
            activity_type="Follow-up",
            is_hidden_from_activity_log=False,
        ))

        time_format = '%d/%m/%Y %I:%M %p'
        success_msg = f"✅ Reminder set for *{lead.company_name}* on {remind_time_local_naive.strftime(time_format)} (Your Local Time)."
        if default_scheduled:
            success_msg += " (Default time used as none was provided)."
            
        return send_message(number=sender, message=success_msg, source=source)

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error setting reminder: {e}", exc_info=True)
        return send_message(number=sender, message="❌ An internal error occurred while setting the reminder.", source=source)