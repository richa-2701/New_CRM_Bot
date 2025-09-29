# reassignment_handler
import logging
import re
from sqlalchemy.orm import Session
from app.crud import get_lead_by_company, get_user_by_phone, get_user_by_name, create_activity_log, create_assignment_log
from app.message_sender import send_message, format_phone, send_whatsapp_message
from app.schemas import ActivityLogCreate, AssignmentLogCreate

logger = logging.getLogger(__name__)

def parse_reassignment_message(msg_text: str) -> tuple[str | None, str | None]:
    """
    Parses messages like "reassign [Company Name] to [Assignee Name/Phone]"
    """
    msg_text = msg_text.strip()
    match = re.search(r"reassign\s+(.+?)\s+to\s+(.+)", msg_text, re.IGNORECASE)
    if match:
        company_raw = match.group(1).strip()
        assignee_raw = match.group(2).strip()
        return company_raw, assignee_raw
    return None, None

async def handle_reassignment(db: Session, message_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    """
    Reassigns a lead to a different user, notifies the new assignee, and confirms with the sender.
    """
    try:
        company_name, new_assignee_input = parse_reassignment_message(message_text)

        if not company_name or not new_assignee_input:
            error_msg = "⚠️ Invalid format. Use: `reassign [Company Name] to [New Assignee]`"
            # Corrected: send_message arguments
            return send_message(number=sender, message=error_msg, source=source)

        lead = get_lead_by_company(db, company_name)
        if not lead:
            # Corrected: send_message arguments
            return send_message(number=sender, message=f"❌ No lead found with company: {company_name}", source=source)

        assignee = None
        if new_assignee_input.isdigit():
            assignee = get_user_by_phone(db, new_assignee_input)
        else:
            assignee = get_user_by_name(db, new_assignee_input)

        if not assignee:
            # Corrected: send_message arguments
            return send_message(number=sender, message=f"❌ Couldn't find user: {new_assignee_input}", source=source)

        old_assignee = lead.assigned_to
        
        # Prevent reassigning to the same person
        if old_assignee.lower() == assignee.username.lower():
            # Corrected: send_message arguments
            return send_message(number=sender, message=f"✅ Lead '{company_name}' is already assigned to {assignee.username}.", source=source)

        lead.assigned_to = assignee.username
        db.commit()

        assignment_log_data = AssignmentLogCreate(
            lead_id=lead.id,
            assigned_to=assignee.username,
            assigned_by=str(sender)
        )
        create_assignment_log(db, log=assignment_log_data)

        activity_details = f"Lead reassigned from '{old_assignee}' to '{assignee.username}' by {sender}."
        create_activity_log(db, activity=ActivityLogCreate(lead_id=lead.id, phase=lead.status, details=activity_details))

        # --- REVISED NOTIFICATION AND RESPONSE LOGIC ---

        # 1. Independent Assignee Notification (always via WhatsApp)
        if assignee.usernumber and assignee.usernumber != sender:
            notification_msg = (
                f"📢 You have been assigned a lead:\n\n"
                f"🏢 Company: *{lead.company_name}*\n"
                f"👤 Contact: {lead.contact_name or 'N/A'}\n"
                f"📞 Phone: {lead.phone or 'N/A'}\n"
                f"📊 Status: {lead.status or 'N/A'}\n"
                f"🔄 Assigned By: {sender}"
            )
            # --- CRITICAL FIX: Corrected send_whatsapp_message call ---
            send_whatsapp_message(number=format_phone(assignee.usernumber), message=notification_msg)
            logger.info(f"Sent reassignment notification to {assignee.username} at {assignee.usernumber}")

        # 2. Confirmation for the Original User (handles both app and WhatsApp)
        confirmation_msg = f"✅ Lead '{company_name}' has been successfully reassigned to {assignee.username}."
        # Corrected: send_message arguments
        return send_message(number=sender, message=confirmation_msg, source=source)

    except Exception as e:
        logger.error("❌ Error in handle_reassignment: %s", str(e), exc_info=True)
        # Corrected: send_message arguments
        return send_message(number=sender, message="❌ An internal error occurred while reassigning the lead.", source=source)