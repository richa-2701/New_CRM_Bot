# app/handlers/activity_handler.py
import re
import logging
from sqlalchemy.orm import Session
from app.crud import get_lead_by_company, create_activity_log, get_user_by_name, get_user_by_phone
from app.schemas import ActivityLogCreate
from app.message_sender import send_message, send_whatsapp_message

logger = logging.getLogger(__name__)

def parse_activity_message(msg_text: str):
    """
    Parses messages like "add activity for [Company Name], [Details]"
    """
    # Using regex to capture company name and the details that follow
    match = re.search(r"add activity for\s+(.+?),\s+(.+)", msg_text, re.IGNORECASE)
    if match:
        company_name = match.group(1).strip()
        details = match.group(2).strip()
        return company_name, details
    return None, None

async def handle_add_activity(db: Session, msg_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    """Handles logging a new activity for a lead and notifies the assignee."""
    try:
        company_name, details = parse_activity_message(msg_text)

        if not company_name or not details:
            error_msg = "⚠️ Invalid format. Please use:\n`add activity for [Company Name], [your activity details]`"
            return send_message(reply_url, sender, error_msg, source)

        # Find the lead by company name
        lead = get_lead_by_company(db, company_name)
        if not lead:
            error_msg = f"❌ Could not find a lead for the company: '{company_name}'. Please check the name."
            return send_message(reply_url, sender, error_msg, source)

        # Create the activity log entry
        activity_data = ActivityLogCreate(
            lead_id=lead.id,
            phase=lead.status,  # Capture the current status/phase of the lead
            details=details
        )
        
        new_activity = create_activity_log(db, activity=activity_data)
        logger.info(f"New activity (ID: {new_activity.id}) created for lead '{lead.company_name}' (ID: {lead.id})")
        
        # --- REVISED NOTIFICATION & RESPONSE LOGIC ---

        # 1. Notify the lead's assignee independently (works for app and WhatsApp)
        if lead.assigned_to:
            assignee_user = get_user_by_name(db, lead.assigned_to)
            sender_user = get_user_by_phone(db, sender) # Try to get sender's name for a nicer message
            
            # Check if assignee exists, has a number, and is not the person logging the activity
            if assignee_user and assignee_user.usernumber and assignee_user.usernumber != sender:
                logged_by_info = sender_user.username if sender_user else sender
                notification_msg = (
                    f"📢 New activity logged for lead *{lead.company_name}*:\n\n"
                    f"'{details}'\n\n"
                    f"- Logged by {logged_by_info}"
                )
                # Use send_whatsapp_message to send notification regardless of source
                send_whatsapp_message(reply_url, assignee_user.usernumber, notification_msg)
                logger.info(f"Sent activity notification to assignee {assignee_user.username}")

        # 2. Send confirmation to the original user
        success_msg = f"✅ Activity logged successfully for *{lead.company_name}*."
        return send_message(reply_url, sender, success_msg, source)

    except Exception as e:
        logger.error(f"Error creating activity log: {e}", exc_info=True)
        error_msg = "❌ An internal error occurred while logging the activity."
        return send_message(reply_url, sender, error_msg, source)