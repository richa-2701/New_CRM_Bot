#qualification_handler.py
import re
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
import dateparser
import logging

from app.gpt_parser import parse_update_company, parse_update_fields
from app.models import Lead, Event
from app.crud import get_lead_by_company, create_event, get_user_by_name, update_lead_status
from app.reminders import schedule_reminder
from app.schemas import EventCreate
from app.message_sender import format_phone, send_message, send_whatsapp_message

logger = logging.getLogger(__name__)

# In-memory temporary context per user. This will store the state.
pending_context = {}

async def handle_qualification(db: Session, msg_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    """
    Handles the entire lead qualification flow, including asking for a company name if missing
    and prompting for additional details after qualification.
    """
    logger.info(f"🔍 Handling qualification for '{msg_text}' from {sender}. Context: {pending_context.get(sender)}")
    
    company_name = None

    if sender in pending_context and pending_context[sender].get("intent") == "qualification_pending":
        company_name = msg_text.strip()
        pending_context.pop(sender, None)
        logger.info(f"✅ Resumed qualification for {sender} with company: {company_name}")
    else:
        company_name = parse_update_company(msg_text)
        logger.info(f"📝 Parsed initial message, found company: '{company_name}'")

    if not company_name:
        pending_context[sender] = {"intent": "qualification_pending"}
        logger.warning(f"⚠️ Company name not found. Prompting user {sender}.")
        return send_message(reply_url, sender, "❌ Couldn't find company name. Please reply with just the company name.", source)

    lead = get_lead_by_company(db, company_name)
    if not lead:
        logger.error(f"❌ Lead not found for company: {company_name}")
        return send_message(reply_url, sender, f"❌ No lead found with company: '{company_name}'. Please check the name and try again.", source)

    update_lead_status(db, lead_id=lead.id, status="Qualified", updated_by=sender)
    
    # --- REVISED LOGIC FOR NOTIFICATIONS AND RESPONSE ---
    
    # 1. Independent Assignee Notification (works for both app and WhatsApp)
    # This now uses send_whatsapp_message directly and does not affect the user response.
    if lead.assigned_to:
        user = get_user_by_name(db, lead.assigned_to)
        if user and user.usernumber and user.usernumber != sender:
            # Using reply_url = "" for app source is fine because send_whatsapp_message will fall back to MAYT_API_URL.
            send_whatsapp_message(
                reply_url,
                format_phone(user.usernumber),
                f"📢 Lead Qualified: The lead for {company_name} has been marked as qualified."
            )

    # 2. Construct a multi-part response for the user.
    reply_parts = [f"✅ Lead for '{company_name}' marked as Qualified."]
    
    missing_fields = []
    if not lead.address: missing_fields.append("Address")
    if not lead.segment: missing_fields.append("Segment")
    if not lead.team_size: missing_fields.append("Team Size")
    if not lead.email: missing_fields.append("Email")
    if not lead.phone_2: missing_fields.append("Alternate Phone (phone_2)")
    if not lead.turnover: missing_fields.append("Turnover")
    if not lead.current_system: missing_fields.append("Current System")
    if not lead.machine_specification: missing_fields.append("Machine Specification")
    if not lead.challenges: missing_fields.append("Challenges")
    if not lead.remark or "No remark provided." in lead.remark: missing_fields.append("Remark")
    
    if missing_fields:
        ask_msg = (
            f"Some details are missing for this lead. If you have them, please provide:\n👉 " +
            ", ".join(missing_fields) + "\n\n(Reply with the details, or type 'skip' if you don't have them.)"
        )
        reply_parts.append(ask_msg)
        pending_context[sender] = {"intent": "awaiting_qualification_details", "company_name": company_name}
    else:
        ask_4_phase_msg = (
            f"All details are complete for {company_name}. Next, do you want to schedule the 4-phase meeting? (Reply with Yes/No)"
        )
        reply_parts.append(ask_4_phase_msg)
        pending_context[sender] = {"intent": "awaiting_4_phase_decision", "company_name": company_name}

    # 3. Combine parts and send a single, unified response.
    final_reply = "\n\n".join(reply_parts)
    return send_message(reply_url, sender, final_reply, source)


async def handle_qualification_update(db: Session, msg_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    """Handles the user's reply (missing details or 'skip') after lead qualification."""
    context = pending_context.get(sender)
    if not context or context.get("intent") != "awaiting_qualification_details":
        return send_message(reply_url, sender, "Sorry, I seem to have lost track. How can I help?", source)

    company_name = context["company_name"]
    pending_context.pop(sender, None)

    reply_parts = []
    negative_keywords = ["no", "skip", "later", "none"]
    if msg_text.lower().strip() in negative_keywords:
        reply_parts.append(f"👍 Understood. No extra details updated for {company_name}.")
    else:
        lead = get_lead_by_company(db, company_name)
        if not lead:
            return send_message(reply_url, sender, f"❌ Strange, I can no longer find the lead for {company_name}. Please start over.", source)

        update_fields, _ = parse_update_fields(msg_text)
        if not update_fields:
            update_fields['remark'] = msg_text.strip()
            logger.info(f"No specific fields found in qualification update. Treating message as remark.")

        updated_fields = []
        for field, value in update_fields.items():
            if hasattr(lead, field) and value:
                if field == 'remark' and lead.remark and "No remark provided." not in lead.remark:
                    setattr(lead, field, f"{lead.remark}\n--\n{value}")
                else:
                    setattr(lead, field, value)
                updated_fields.append(field.replace('_', ' ').title())
        
        if not updated_fields:
            reply_parts.append("⚠️ I couldn't find any valid fields to update from your message. Let's move on for now.")
        else:
            db.commit()
            reply_parts.append(f"✅ Details for '{company_name}' updated: {', '.join(updated_fields)}.")

    # Always ask about the 4-phase meeting after handling details.
    ask_4_phase_msg = (
        f"Next, do you want to schedule the 4-phase meeting for *{company_name}*? (Reply with Yes/No)"
    )
    reply_parts.append(ask_4_phase_msg)
    
    # Set context for the next step
    pending_context[sender] = {"intent": "awaiting_4_phase_decision", "company_name": company_name}
    logger.info(f"Set context for {sender} to 'awaiting_4_phase_decision' for company '{company_name}'")

    # Combine parts and send a single, unified response.
    final_reply = "\n\n".join(reply_parts)
    return send_message(reply_url, sender, final_reply, source)


async def handle_4_phase_decision(db: Session, msg_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    """Handles the user's Yes/No reply to scheduling a 4-phase meeting."""
    context = pending_context.get(sender)
    if not context or context.get("intent") != "awaiting_4_phase_decision":
        return send_message(reply_url, sender, "Sorry, I seem to have lost track. How can I help?", source)

    company_name = context["company_name"]
    pending_context.pop(sender, None)

    lead = get_lead_by_company(db, company_name)
    if not lead:
        return send_message(reply_url, sender, f"❌ Strange, I can no longer find the lead for {company_name}. Please start over.", source)

    final_reply = ""
    positive_keywords = ["yes", "y", "ok", "okay", "sure", "do it", "schedule", "yes please"]
    
    if any(keyword in msg_text.lower().strip() for keyword in positive_keywords):
        logger.info(f"User {sender} agreed to schedule 4-phase meeting for {company_name}. Prompting for command.")
        final_reply = (
            f"👍 Great! To schedule the 4-Phase Meeting for *{company_name}*, please use the command:\n\n"
            f"\"Schedule meeting with {company_name} on [Date and Time] assigned to [Person]\""
        )
    else:
        logger.info(f"User {sender} skipped the 4-phase meeting for {company_name}.")
        # Construct a combined response for skipping
        reply_parts = [
            f"👍 Understood. We will skip the 4-phase meeting for now.",
            (f"The next step is to schedule a demo. You can use:\n"
             f"\"Schedule demo for {company_name} on [Date and Time] assigned to [Person Name]\"")
        ]
        final_reply = "\n\n".join(reply_parts)

    return send_message(reply_url, sender, final_reply, source)