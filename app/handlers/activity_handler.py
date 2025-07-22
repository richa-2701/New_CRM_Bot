# app/handlers/activity_handler.py
import re
import logging
from sqlalchemy.orm import Session
from app.crud import get_lead_by_company, create_activity_log
from app.schemas import ActivityLogCreate
from app.message_sender import send_message

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
    """Handles logging a new activity for a lead."""
    company_name, details = parse_activity_message(msg_text)

    if not company_name or not details:
        error_msg = "⚠️ Invalid format. Please use:\n`add activity for [Company Name], [your activity details]`"
        response = send_message(reply_url, sender, error_msg, source)
        if source.lower() == "app":
            return response
        return {"status": "error", "message": "Invalid format for adding activity."}

    # Find the lead by company name
    lead = get_lead_by_company(db, company_name)
    if not lead:
        error_msg = f"❌ Could not find a lead for the company: '{company_name}'. Please check the name."
        response = send_message(reply_url, sender, error_msg, source)
        if source.lower() == "app":
            return response
        return {"status": "error", "message": "Lead not found."}

    # Create the activity log entry
    activity_data = ActivityLogCreate(
        lead_id=lead.id,
        phase=lead.status,  # Capture the current status/phase of the lead
        details=details
    )
    
    try:
        new_activity = create_activity_log(db, activity=activity_data)
        logger.info(f"New activity (ID: {new_activity.id}) created for lead '{lead.company_name}' (ID: {lead.id})")
        
        # Send confirmation message
        success_msg = f"✅ Activity logged successfully for *{lead.company_name}*."
        response = send_message(reply_url, sender, success_msg, source)
        if source.lower() == "app":
            return response
        return {"status": "success"}

    except Exception as e:
        logger.error(f"Error creating activity log: {e}", exc_info=True)
        error_msg = "❌ An internal error occurred while logging the activity."
        response = send_message(reply_url, sender, error_msg, source)
        if source.lower() == "app":
            return response
        return {"status": "error", "details": str(e)}