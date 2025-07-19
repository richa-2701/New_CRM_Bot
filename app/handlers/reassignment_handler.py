# app/handlers/reassignment_handler.py
import logging
import re
from sqlalchemy.orm import Session
from app.crud import get_lead_by_company, get_user_by_phone, get_user_by_name
from app.message_sender import send_whatsapp_message, format_phone

logger = logging.getLogger(__name__)

def parse_reassignment_message(msg_text: str) -> tuple[str | None, str | None]:
    msg_text = msg_text.strip()

    # Lowercased backup for keyword detection
    msg_lower = msg_text.lower()

    # Use regex to find company and assignee
    match = re.search(r"reassign\s+(.*?)\s+to\s+(.*)", msg_text, re.IGNORECASE)
    if match:
        company_raw = match.group(1).strip()
        assignee_raw = match.group(2).strip()
        return company_raw, assignee_raw

    # Try fallback comma/colon/newline-based split
    tokens = [x.strip() for x in re.split(r"[,:;\n]", msg_text) if x.strip()]
    if len(tokens) >= 2:
        return tokens[0], tokens[1]

    return None, None

async def handle_reassignment(db: Session, message_text: str, sender: str, reply_url: str):
    """
    Reassigns a lead to a different user.

    Accepts flexible input like:
    - Reassign Parksons to Richa
    - Company: Parksons
      Assigned To: Richa
    - Parksons, Richa
    """

    try:
        # 🔍 Extract company and assignee using smart parser
        company_name, new_assignee_input = parse_reassignment_message(message_text)

        if not company_name or not new_assignee_input:
            send_whatsapp_message(reply_url, sender, "⚠️ Please specify both Company and new Assignee.")
            return {"status": "error", "detail": "Missing company or assignee"}

        # ✅ Find the lead
        lead = get_lead_by_company(db, company_name)
        if not lead:
            send_whatsapp_message(reply_url, sender, f"❌ No lead found with company: {company_name}")
            return {"status": "error", "detail": "Lead not found"}

        # ✅ Find the user by number or name
        assignee = None
        if new_assignee_input.isdigit():
            assignee = get_user_by_phone(db, new_assignee_input)
        else:
            assignee = get_user_by_name(db, new_assignee_input)

        if not assignee:
            send_whatsapp_message(reply_url, sender, f"❌ Couldn't find user: {new_assignee_input}")
            return {"status": "error", "detail": "Assignee not found"}

        # ✅ Reassign in DB
        lead.assigned_to = assignee.username
        db.commit()

        # ✅ Notify sender
        send_whatsapp_message(reply_url, sender, f"✅ Lead '{company_name}' reassigned to {assignee.username}")

        # ✅ Notify assignee with full lead details
        if assignee.usernumber:
            phone_formatted = format_phone(assignee.usernumber)

            message = (
                f"📢 You have been reassigned a lead:\n\n"
                f"🏢 Company: {lead.company_name}\n"
                f"👤 Contact: {lead.contact_name or 'N/A'}\n"
                f"📞 Phone: {lead.phone or 'N/A'}\n"
                f"📊 Status: {lead.status or 'N/A'}\n"
                f"🔄 Assigned By: {sender}\n"
            )
            send_whatsapp_message(reply_url, phone_formatted, message)

        return {"status": "success", "message": f"Lead '{company_name}' reassigned to {assignee.username}"}

    except Exception as e:
        logger.error("❌ Error in handle_reassignment: %s", str(e), exc_info=True)
        send_whatsapp_message(reply_url, sender, "❌ Failed to reassign lead.")
        return {"status": "error", "detail": str(e)}
