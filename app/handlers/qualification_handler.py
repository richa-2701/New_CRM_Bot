# qualification_handler
import re
from typing import Optional
from sqlalchemy.orm import Session
import logging
from app.gpt_parser import parse_update_company, parse_update_fields
from app.models import Lead, Event, User
from app.crud import get_lead_by_company, create_event, get_user_by_name, update_lead_status, get_user_by_phone # Added get_user_by_phone
from app.schemas import EventCreate
from app.message_sender import format_phone, send_message, send_whatsapp_message

logger = logging.getLogger(__name__)

pending_context = {}


async def handle_unqualification(db: Session, msg_text: str, sender: str, reply_url: str, source: str, status: str):
    """
    Handles marking a lead as 'unqualified' or 'not_our_segment'.
    'status' will be either 'unqualified' or 'not_our_segment'.
    """
    company_name = parse_update_company(msg_text)
    
    if not company_name:
        # If company name is missing, we can ask for it.
        context_key = "unqualification_pending" if status == "unqualified" else "segment_pending"
        pending_context[sender] = {"intent": context_key}
        # Corrected: send_message arguments
        return send_message(number=sender, message="Which company are you referring to?", source=source)

    lead = get_lead_by_company(db, company_name)
    if not lead:
        # Corrected: send_message arguments
        return send_message(number=sender, message=f"❌ No lead found for company: '{company_name}'.", source=source)
    
    # Determine the human-readable status for the message
    status_text = "Not Qualified" if status == "unqualified" else "Not Our Segment"

    # Update the lead status using the provided status parameter
    update_lead_status(db, lead_id=lead.id, status=status, updated_by=str(sender))

    # Clear any pending context for this user
    pending_context.pop(sender, None)

    # Notify the original assignee if they are not the one updating the status
    if lead.assigned_to:
        assignee = get_user_by_name(db, lead.assigned_to)
        sender_user = db.query(User).filter(User.usernumber == sender).first()
        sender_name = sender_user.username if sender_user else str(sender)

        if assignee and assignee.username != sender_name:
            notification = f"📢 Lead Status Update: The lead for '{company_name}' has been marked as '{status_text}' by {sender_name}."
            # --- CRITICAL FIX: Corrected send_whatsapp_message call ---
            send_whatsapp_message(number=assignee.usernumber, message=notification)

    # Corrected: send_message arguments
    return send_message(number=sender, message=f"✅ Understood. Lead for '{company_name}' has been marked as '{status_text}'.", source=source)


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
        # Corrected: send_message arguments
        return send_message(number=sender, message="❌ Couldn't find company name. Please reply with just the company name.", source=source)

    lead = get_lead_by_company(db, company_name)
    if not lead:
        logger.error(f"❌ Lead not found for company: {company_name}")
        # Corrected: send_message arguments
        return send_message(number=sender, message=f"❌ No lead found with company: '{company_name}'. Please check the name and try again.", source=source)

    update_lead_status(db, lead_id=lead.id, status="Qualified", updated_by=str(sender))
    
    # --- Independent Assignee Notification ---
    if lead.assigned_to:
        user = get_user_by_name(db, lead.assigned_to)
        # Ensure sender is a string for comparison
        sender_identifier = str(sender)
        if user and user.usernumber and user.usernumber != sender_identifier:
            # --- CRITICAL FIX: Corrected send_whatsapp_message call ---
            send_whatsapp_message(
                number=format_phone(user.usernumber),
                message=f"📢 Lead Qualified: The lead for {company_name} has been marked as qualified."
            )

    reply_parts = [f"✅ Lead for '{company_name}' marked as Qualified."]
    
    missing_fields = []
    if not lead.address: missing_fields.append("Address")
    if not lead.segment: missing_fields.append("Segment")
    if not lead.team_size: missing_fields.append("Team Size")
    if not lead.turnover: missing_fields.append("Turnover")
    if not lead.current_system: missing_fields.append("Current System")
    if not lead.machine_specification: missing_fields.append("Machine Specification")
    if not lead.challenges: missing_fields.append("Challenges")
    
    # --- CORRECTION: Check for contact email properly ---
    # lead.contacts is a relationship, it needs to be accessed to load the list.
    # It might be an empty list if no contacts exist.
    if lead.contacts:
        primary_contact = lead.contacts[0]
        if not primary_contact.email:
            missing_fields.append("Email for primary contact")
    else: # If there are no contacts at all
        missing_fields.append("Primary Contact Details (Phone, Email)")
    # --- END CORRECTION ---
    
    if not lead.remark or "No remark provided." in lead.remark:
        missing_fields.append("Remark")
    
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

    final_reply = "\n\n".join(reply_parts)
    # Corrected: send_message arguments
    return send_message(number=sender, message=final_reply, source=source)


async def handle_qualification_update(db: Session, msg_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    context = pending_context.get(sender)
    if not context or context.get("intent") != "awaiting_qualification_details":
        # Corrected: send_message arguments
        return send_message(number=sender, message="Sorry, I seem to have lost track. How can I help?", source=source)

    company_name = context["company_name"]
    pending_context.pop(sender, None)

    reply_parts = []
    negative_keywords = ["no", "skip", "later", "none"]
    if msg_text.lower().strip() in negative_keywords:
        reply_parts.append(f"👍 Understood. No extra details updated for {company_name}.")
    else:
        lead = get_lead_by_company(db, company_name)
        if not lead:
            # Corrected: send_message arguments
            return send_message(number=sender, message=f"❌ Strange, I can no longer find the lead for {company_name}. Please start over.", source=source)

        update_fields, _ = parse_update_fields(msg_text)
        if not update_fields:
            # If no specific fields were parsed, consider the entire message a remark.
            # Only do this if the message is not a negative keyword (already checked above)
            if msg_text.strip(): # Ensure there's actual content to add as a remark
                update_fields['remark'] = msg_text.strip()
                logger.info(f"No specific fields found in qualification update. Treating message as remark.")

        updated_fields = []
        for field, value in update_fields.items():
            # Check if lead.contacts exists before trying to access lead.contacts[0].email
            if field == 'email' and lead.contacts:
                primary_contact = lead.contacts[0]
                primary_contact.email = value
                # db.commit() will save this change when lead is committed
                updated_fields.append("Primary Contact Email")
            elif hasattr(lead, field) and value:
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

    ask_4_phase_msg = (
        f"Next, do you want to schedule the 4-phase meeting for *{company_name}*? (Reply with Yes/No)"
    )
    reply_parts.append(ask_4_phase_msg)
    
    pending_context[sender] = {"intent": "awaiting_4_phase_decision", "company_name": company_name}
    logger.info(f"Set context for {sender} to 'awaiting_4_phase_decision' for company '{company_name}'")

    final_reply = "\n\n".join(reply_parts)
    # Corrected: send_message arguments
    return send_message(number=sender, message=final_reply, source=source)


async def handle_4_phase_decision(db: Session, msg_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    context = pending_context.get(sender)
    if not context or context.get("intent") != "awaiting_4_phase_decision":
        # Corrected: send_message arguments
        return send_message(number=sender, message="Sorry, I seem to have lost track. How can I help?", source=source)

    company_name = context["company_name"]
    pending_context.pop(sender, None)

    lead = get_lead_by_company(db, company_name)
    if not lead:
        # Corrected: send_message arguments
        return send_message(number=sender, message=f"❌ Strange, I can no longer find the lead for {company_name}. Please start over.", source=source)

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
        reply_parts = [
            f"👍 Understood. We will skip the 4-phase meeting for now.",
            (f"The next step is to schedule a demo. You can use:\n"
             f"\"Schedule demo for {company_name} on [Date and Time] assigned to [Person Name]\"")
        ]
        final_reply = "\n\n".join(reply_parts)

    # Corrected: send_message arguments
    return send_message(number=sender, message=final_reply, source=source)