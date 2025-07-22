import re
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
import dateparser
import logging

from app.gpt_parser import parse_update_company, parse_update_fields
from app.models import Lead, Event
# --- MODIFIED: Import the centralized status updater ---
from app.crud import get_lead_by_company, create_event, get_user_by_name, update_lead_status
# This import seems unused here, but we will leave it as is.
from app.reminders import schedule_reminder
from app.schemas import EventCreate
from app.message_sender import format_phone, send_message

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

    # Step 1: Check if this is a follow-up message for a pending qualification.
    if sender in pending_context and pending_context[sender].get("intent") == "qualification_pending":
        company_name = msg_text.strip()
        pending_context.pop(sender, None)
        logger.info(f"✅ Resumed qualification for {sender} with company: {company_name}")
    else:
        company_name = parse_update_company(msg_text)
        logger.info(f"📝 Parsed initial message, found company: '{company_name}'")

    # Step 3: If no company name could be found, ask the user for it.
    if not company_name:
        pending_context[sender] = {"intent": "qualification_pending"}
        logger.warning(f"⚠️ Company name not found. Prompting user {sender}.")
        response = send_message(reply_url, sender, "❌ Couldn't find company name. Please reply with just the company name.")
        if source.lower() == "app":
            return response
        return {"status": "awaiting_company_name"}

    # --- If we reach this point, we have a valid company name ---

    # Step 4: Proceed with the qualification logic.
    lead = get_lead_by_company(db, company_name)
    if not lead:
        logger.error(f"❌ Lead not found for company: {company_name}")
        response = send_message(reply_url, sender, f"❌ No lead found with company: '{company_name}'. Please check the name and try again.")
        if source.lower() == "app":
            return response
        return {"status": "error", "message": "Lead not found"}

    # --- CORRECTED LOGIC: Use centralized function to update status and log activity ---
    # This single line replaces the direct status update, commit, and refresh.
    update_lead_status(db, lead_id=lead.id, status="Qualified", updated_by=sender)
    
    # Send the qualification confirmation message first.
    confirmation_message = f"✅ Lead for '{company_name}' marked as Qualified."
    send_message(reply_url, sender, confirmation_message, source)
    
    logger.info(f"🎉 Successfully qualified lead '{company_name}' for user {sender}.")

    # NEW: Check for ALL missing fields and ask user for them.
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
        send_message(reply_url, sender, ask_msg, source)
        # Store context to handle the next message as an update.
        pending_context[sender] = {"intent": "awaiting_qualification_details", "company_name": company_name}
        if source.lower() == "app":
            return {"status": "success", "next_action": "awaiting_qualification_details"}
    else:
        # If no missing fields, prompt for 4-phase meeting directly.
        ask_4_phase_msg = (
            f"All details are complete for {company_name}. Next, do you want to schedule the 4-phase meeting? (Reply with Yes/No)"
        )
        send_message(reply_url, sender, ask_4_phase_msg, source)
        pending_context[sender] = {"intent": "awaiting_4_phase_decision", "company_name": company_name}
        if source.lower() == "app":
            return {"status": "success", "next_action": "awaiting_4_phase_decision"}


    # 🔔 (Optional) Notify the assignee
    if lead.assigned_to:
        user = get_user_by_name(db, lead.assigned_to)
        if user and user.usernumber and user.usernumber != sender:
            send_message(
                reply_url,
                format_phone(user.usernumber),
                f"📢 Lead Qualified: The lead for {company_name} has been marked as qualified and is assigned to you."
            )

    return {"status": "success"}


# This function handles the user's reply after being prompted for missing details.
async def handle_qualification_update(db: Session, msg_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    """Handles the user's reply (missing details or 'skip') after lead qualification."""
    context = pending_context.get(sender)
    if not context or context.get("intent") != "awaiting_qualification_details":
        response = send_message(reply_url, sender, "Sorry, I seem to have lost track. How can I help?")
        if source.lower() == "app":
            return response
        return {"status": "error", "message": "Context not found"}

    company_name = context["company_name"]
    # Clean up context immediately to prevent loops.
    pending_context.pop(sender, None)

    # Check for negative/skip response.
    negative_keywords = ["no", "skip", "later", "none", "don't have", "dont have"]
    if any(keyword in msg_text.lower().strip() for keyword in negative_keywords):
        send_message(reply_url, sender, f"👍 Understood. No extra details updated for {company_name}.", source)
    else:
        # If not a skip, process the update.
        lead = get_lead_by_company(db, company_name)
        if not lead:
            response = send_message(reply_url, sender, f"❌ Strange, I can no longer find the lead for {company_name}. Please start over.", source)
            if source.lower() == "app":
                return response
            return {"status": "error", "message": f"Lead not found for {company_name}"}

        update_fields, _ = parse_update_fields(msg_text)
        
        updated_fields = []
        for field, value in update_fields.items():
            if hasattr(lead, field) and value:
                setattr(lead, field, value)
                updated_fields.append(field.replace('_', ' ').title())
        
        if not updated_fields:
            send_message(reply_url, sender, "⚠️ I couldn't find any valid fields to update from your message. Let's move on for now.", source)
        else:
            db.commit()
            send_message(reply_url, sender, f"✅ Details for '{company_name}' updated: {', '.join(updated_fields)}.", source)

    # After handling details, ask about the 4-phase meeting.
    ask_4_phase_msg = (
        f"Next, do you want to schedule the 4-phase meeting for *{company_name}*? (Reply with Yes/No)"
    )
    send_message(reply_url, sender, ask_4_phase_msg, source)

    # Set context for the next step
    pending_context[sender] = {"intent": "awaiting_4_phase_decision", "company_name": company_name}
    logger.info(f"Set context for {sender} to 'awaiting_4_phase_decision' for company '{company_name}'")

    if source.lower() == "app":
        # For app, we might just return a status indicating what we're waiting for
        return {"status": "success", "next_action": "awaiting_4_phase_decision"}

    return {"status": "success", "message": "Qualification update handled, awaiting 4-phase decision."}


async def handle_4_phase_decision(db: Session, msg_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    """Handles the user's Yes/No reply to scheduling a 4-phase meeting."""
    context = pending_context.get(sender)
    if not context or context.get("intent") != "awaiting_4_phase_decision":
        response = send_message(reply_url, sender, "Sorry, I seem to have lost track. How can I help?")
        if source.lower() == "app":
            return response
        return {"status": "error", "message": "Context not found"}

    company_name = context["company_name"]
    # Clean up context immediately.
    pending_context.pop(sender, None)

    lead = get_lead_by_company(db, company_name)
    if not lead:
        response = send_message(reply_url, sender, f"❌ Strange, I can no longer find the lead for {company_name}. Please start over.")
        if source.lower() == "app":
            return response
        return {"status": "error", "message": f"Lead not found for {company_name}"}

    positive_keywords = ["yes", "y", "ok", "okay", "sure", "do it", "schedule", "yes please"]
    
    # --- MODIFIED LOGIC ---
    # If user agrees to schedule the 4-phase meeting
    if any(keyword in msg_text.lower().strip() for keyword in positive_keywords):
        logger.info(f"User {sender} agreed to schedule 4-phase meeting for {company_name}. Prompting for command.")
        
        # DO NOT auto-schedule. Instead, prompt the user to do it.
        prompt_schedule_message = (
            f"👍 Great! To schedule the 4-Phase Meeting for *{company_name}*, please use the command:\n\n"
            f"\"Schedule meeting with {company_name} on [Date and Time] assigned to [Person]\""
        )
        response = send_message(reply_url, sender, prompt_schedule_message, source)
        if source.lower() == "app":
            return response

    # If user skips or says no
    else:
        logger.info(f"User {sender} skipped the 4-phase meeting for {company_name}.")
        send_message(
            reply_url,
            sender,
            f"👍 Understood. We will skip the 4-phase meeting.",
            source
        )

        # Prompt for demo scheduling ONLY if the meeting is skipped.
        prompt_demo_msg = (
            f"The next step is to schedule a demo. You can use:\n"
            f"\"Schedule demo for {company_name} on [Date and Time] assigned to [Person Name]\""
        )
        response = send_message(reply_url, sender, prompt_demo_msg, source)
        if source.lower() == "app":
            return response

    return {"status": "success", "message": "4-phase decision handled"}