# app/handlers/activity_handler.py

import re
import logging
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from dateparser.search import search_dates

from app.crud import get_lead_by_company, create_activity_log, get_user_by_name, get_user_by_phone, create_reminder
from app.schemas import ActivityLogCreate, ReminderCreate
from app.message_sender import send_message, send_whatsapp_message

logger = logging.getLogger(__name__)

def parse_activity_message(msg_text: str):
    """
    Parses messages like "add activity for [Company Name], [Details]"
    """
    match = re.search(r"add activity for\s+(.+?),\s+(.+)", msg_text, re.IGNORECASE)
    if match:
        company_name = match.group(1).strip()
        details = match.group(2).strip()
        return company_name, details
    return None, None

async def handle_add_activity(db: Session, msg_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    """
    Handles logging a new activity for a lead. If a date is found in the
    activity details, it automatically schedules reminders for the assignee.
    """
    try:
        company_name, details = parse_activity_message(msg_text)

        if not company_name or not details:
            error_msg = "⚠️ Invalid format. Please use:\n`add activity for [Company Name], [your activity details]`"
            return send_message(reply_url, sender, error_msg, source)

        lead = get_lead_by_company(db, company_name)
        if not lead:
            error_msg = f"❌ Could not find a lead for the company: '{company_name}'. Please check the name."
            return send_message(reply_url, sender, error_msg, source)

        activity_data = ActivityLogCreate(
            lead_id=lead.id,
            phase=lead.status,
            details=details
        )
        
        new_activity = create_activity_log(db, activity=activity_data)
        logger.info(f"New activity (ID: {new_activity.id}) created for lead '{lead.company_name}' (ID: {lead.id})")
        
        reminder_set = False
        remind_time = None
        
        # --- THIS IS THE CORRECTED AND FINAL LOGIC BLOCK ---

        # 1. Pre-filter using a regex to find phrases that are LIKELY to contain a date.
        # We look for common trigger words.
        date_trigger_pattern = r'\b(on|at|in|next|tomorrow|today|by)\b'
        match = re.search(date_trigger_pattern, details, re.IGNORECASE)

        # 2. ONLY if a trigger word is found, do we proceed to parse the date.
        if match:
            # Pre-process the details to correct common typos for better parsing.
            corrected_details = details.lower().replace("tommorow", "tomorrow")

            # Now, parse the date from the corrected text.
            parsed_dates = search_dates(corrected_details, settings={'PREFER_DATES_FROM': 'future'})
            
            if parsed_dates:
                remind_time = parsed_dates[0][1]
                
                if lead.assigned_to:
                    assignee_user = get_user_by_name(db, lead.assigned_to)
                    if assignee_user:
                        reminder_message = f"Regarding *{lead.company_name}*: {details}"
                        
                        create_reminder(db, ReminderCreate(
                            lead_id=lead.id, user_id=assignee_user.id, assigned_to=assignee_user.username,
                            remind_time=remind_time, message=reminder_message
                        ))

                        one_hour_before = remind_time - timedelta(hours=1)
                        if one_hour_before > datetime.utcnow():
                            create_reminder(db, ReminderCreate(
                                lead_id=lead.id, user_id=assignee_user.id, assigned_to=assignee_user.username,
                                remind_time=one_hour_before, message=f"(in 1 hour) {reminder_message}"
                            ))
                        
                        logger.info(f"Scheduled reminder for activity on lead {lead.id} for assignee {assignee_user.username}")
                        reminder_set = True
        # --- END CORRECTION ---

        if lead.assigned_to:
            assignee_user = get_user_by_name(db, lead.assigned_to)
            sender_user = get_user_by_phone(db, sender)
            sender_identifier = str(sender)

            if assignee_user and assignee_user.usernumber and assignee_user.usernumber != sender_identifier:
                logged_by_info = sender_user.username if sender_user else sender_identifier
                notification_msg = (
                    f"📢 New activity logged for lead *{lead.company_name}*:\n\n"
                    f"'{details}'\n\n"
                    f"- Logged by {logged_by_info}"
                )
                send_whatsapp_message(reply_url, assignee_user.usernumber, notification_msg)
                logger.info(f"Sent activity notification to assignee {assignee_user.username}")

        success_msg = f"✅ Activity logged successfully for *{lead.company_name}*."
        if reminder_set and remind_time:
            success_msg += f"\n\n⏰ Reminder has also been set for the assignee for {remind_time.strftime('%A, %b %d at %I:%M %p')}."

        return send_message(reply_url, sender, success_msg, source)

    except Exception as e:
        logger.error(f"Error creating activity log: {e}", exc_info=True)
        db.rollback()
        error_msg = "❌ An internal error occurred while logging the activity."
        return send_message(reply_url, sender, error_msg, source)