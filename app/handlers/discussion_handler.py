# discussion_handler
import re
import logging
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from dateparser.search import search_dates

from app.crud import get_lead_by_company, create_activity_log, get_user_by_name, create_reminder, find_and_complete_reminder
from app.schemas import ActivityLogCreate, ReminderCreate
from app.message_sender import send_message # Only send_message is needed here

logger = logging.getLogger(__name__)

# --- PARSER FUNCTIONS ---

def parse_log_or_done_message(command: str, msg_text: str):
    """Parses "log discussion for [Company], [Details]" or "discussion done for [Company], [Details]" """
    pattern = re.compile(rf"{command}\s+for\s+(.+?),\s*(.+)", re.IGNORECASE)
    match = pattern.search(msg_text)
    if match:
        company_name = match.group(1).strip()
        details = match.group(2).strip()
        return company_name, details
    return None, None

def parse_schedule_message(msg_text: str):
    """Parses "schedule discussion for [Company], [Details with date]" """
    return parse_log_or_done_message("schedule discussion", msg_text)


# --- HANDLER FUNCTIONS ---

async def handle_log_discussion(db: Session, msg_text: str, sender: str, reply_url: str, source: str):
    """Handles logging a discussion that has already happened."""
    company_name, details = parse_log_or_done_message("log discussion", msg_text)
    if not company_name:
        # Corrected: send_message arguments
        return send_message(number=sender, message="⚠️ Invalid format. Use: `log discussion for [Company], [details]`", source=source)

    lead = get_lead_by_company(db, company_name)
    if not lead:
        # Corrected: send_message arguments
        return send_message(number=sender, message=f"❌ Lead not found for '{company_name}'.", source=source)

    # Log the discussion as a completed activity
    create_activity_log(db, ActivityLogCreate(
        lead_id=lead.id,
        phase="Discussion Logged",
        details=details
    ))

    # Corrected: send_message arguments
    return send_message(number=sender, message=f"✅ Discussion for *{lead.company_name}* has been logged.", source=source)


async def handle_schedule_discussion(db: Session, msg_text: str, sender: str, reply_url: str, source: str):
    """Handles scheduling a future discussion and sets a reminder."""
    company_name, details = parse_schedule_message(msg_text)
    if not company_name:
        # Corrected: send_message arguments
        return send_message(number=sender, message="⚠️ Invalid format. Use: `schedule discussion for [Company], [details including date/time]`", source=source)
    
    lead = get_lead_by_company(db, company_name)
    if not lead:
        # Corrected: send_message arguments
        return send_message(number=sender, message=f"❌ Lead not found for '{company_name}'.", source=source)

    # Find a date in the details
    parsed_dates = search_dates(details, settings={'PREFER_DATES_FROM': 'future'})
    if not parsed_dates:
        # Corrected: send_message arguments
        return send_message(number=sender, message="⚠️ No future date found in the details. Please specify when to schedule the discussion (e.g., 'tomorrow at 2pm').", source=source)

    remind_time = parsed_dates[0][1]
    assignee_user = get_user_by_name(db, lead.assigned_to)

    if not assignee_user:
        # Corrected: send_message arguments
        return send_message(number=sender, message=f"❌ Cannot find assignee '{lead.assigned_to}' to set reminder.", source=source)

    # 1. Log the activity that the discussion has been scheduled
    create_activity_log(db, ActivityLogCreate(
        lead_id=lead.id,
        phase="Discussion Scheduled",
        details=f"Scheduled discussion: {details}"
    ))

    # 2. Create the reminder for the assignee
    reminder_message = f"Upcoming discussion for *{lead.company_name}*: {details}"
    create_reminder(db, ReminderCreate(
        lead_id=lead.id,
        user_id=assignee_user.id,
        assigned_to=assignee_user.username,
        remind_time=remind_time,
        message=reminder_message
    ))

    success_msg = f"✅ Discussion for *{lead.company_name}* has been scheduled.\n\n⏰ A reminder has been set for the assignee for {remind_time.strftime('%A, %b %d at %I:%M %p')}."
    # Corrected: send_message arguments
    return send_message(number=sender, message=success_msg, source=source)


async def handle_discussion_done(db: Session, msg_text: str, sender: str, reply_url: str, source: str):
    """Handles marking a previously scheduled discussion as complete."""
    company_name, details = parse_log_or_done_message("discussion done", msg_text)
    if not company_name:
        # Corrected: send_message arguments
        return send_message(number=sender, message="⚠️ Invalid format. Use: `discussion done for [Company], [outcome notes]`", source=source)

    lead = get_lead_by_company(db, company_name)
    if not lead:
        # Corrected: send_message arguments
        return send_message(number=sender, message=f"❌ Lead not found for '{company_name}'.", source=source)
    
    # 1. Log the completion activity
    create_activity_log(db, ActivityLogCreate(
        lead_id=lead.id,
        phase="Discussion Done",
        details=f"Outcome: {details}"
    ))

    # 2. Try to find and complete any related pending reminders
    reminder_completed = find_and_complete_reminder(db, lead.id, message_like="%discussion for%")
    
    success_msg = f"✅ Discussion outcome for *{lead.company_name}* has been logged."
    if reminder_completed:
        success_msg += "\n\nThe scheduled reminder for this discussion has been marked as complete."

    # Corrected: send_message arguments
    return send_message(number=sender, message=success_msg, source=source)