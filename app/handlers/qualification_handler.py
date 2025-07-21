# app/handlers/qualification_handler.py
import re
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
import dateparser
import logging

from app.gpt_parser import parse_update_company, parse_update_fields
from app.models import Lead
from app.crud import get_lead_by_company, create_event, get_user_by_name
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

    # Step 5: Update lead status and other details.
    lead.status = "qualified"
    assigned_to = lead.assigned_to or "8878433436"
    lead.assigned_to = assigned_to
    db.commit()
    db.refresh(lead)

    # 🗓️ Create event (Example) - THIS IS NOW DISABLED AS PER REQUEST
    # logger.info("✅ 4-Phase Meeting auto-scheduling is now disabled.")
    # event_start = datetime.now() + timedelta(hours=1)
    # event_end = event_start + timedelta(minutes=20)
    # event = EventCreate(
    #     lead_id=lead.id,
    #     assigned_to=assigned_to,
    #     event_type="4 Phase Meeting",
    #     event_time=event_start,
    #     event_end_time=event_end,
    #     created_by=sender,
    #     remark=f"Auto-scheduled: 4 Phase Meeting for {company_name}",
    # )
    # create_event(db, event)
    
    # Send the qualification confirmation message first.
    confirmation_message = f"✅ Lead for '{company_name}' marked as qualified."
    response = send_message(reply_url, sender, confirmation_message)
    0
    logger.info(f"🎉 Successfully qualified lead '{company_name}' for user {sender}.")

    # NEW: Check for missing fields and ask user for them.
    missing_fields = []
    if not lead.address: missing_fields.append("Address")
    if not lead.segment: missing_fields.append("Segment")
    if not lead.team_size: missing_fields.append("Team Size")
    if not lead.email: missing_fields.append("Email")
    if not lead.remark or lead.remark == "No remark provided.": missing_fields.append("Remark")
    
    if missing_fields:
        ask_msg = (
            f"Some details are missing for this lead. If you have them, please provide:\n👉 " +
            ", ".join(missing_fields) + "\n\n(Reply with the details, or type 'skip' if you don't have them.)"
        )
        response = send_message(reply_url, sender, ask_msg)
        # Store context to handle the next message as an update.
        if source.lower() == "app":
            return response
        pending_context[sender] = {"intent": "awaiting_qualification_details", "company_name": company_name}
    else:
        # If no missing fields, prompt for meeting directly.
        prompt_meeting_msg = (
            f"All details are complete for {company_name}. To schedule the next meeting, use:\n"
            f"'Schedule meeting with {company_name} assigned to [Person] on [Date/Time]'"
        )
        response = send_message(reply_url, sender, prompt_meeting_msg)
        if source.lower() == "app":
            return response

    # 🔔 (Optional) Notify the assignee
    if assigned_to:
        user = get_user_by_name(db, assigned_to)
        if user and user.usernumber and user.usernumber != sender:
            response = send_message(
                reply_url,
                format_phone(user.usernumber),
                f"📢 Lead Qualified: The lead for {company_name} has been marked as qualified and is assigned to you."
            )
            if source.lower() == "app":
                return response

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
        response = send_message(reply_url, sender, f"👍 Understood. No extra details updated for {company_name}.")
        if source.lower() == "app":
            return response
    else:
        # If not a skip, process the update.
        lead = get_lead_by_company(db, company_name)
        if not lead:
            response = send_message(reply_url, sender, f"❌ Strange, I can no longer find the lead for {company_name}. Please start over.")
            if source.lower() == "app":
                return response
            return {"status": "error", "message": f"Lead not found for {company_name}"}

        update_fields = parse_update_fields(msg_text)
        
        updated_fields = []
        for field, value in update_fields.items():
            if hasattr(lead, field) and value:
                setattr(lead, field, value)
                updated_fields.append(field.replace('_', ' ').title())
        
        if not updated_fields:
            response = send_message(reply_url, sender, "⚠️ I couldn't find any valid fields to update from your message. Let's move on for now.")
            if source.lower() == "app":
                return response
        else:
            db.commit()
            response = send_message(reply_url, sender, f"✅ Details for '{company_name}' updated: {', '.join(updated_fields)}.")
            if source.lower() == "app":
                return response

    # In all cases (skip or update), prompt for the next step: scheduling a meeting.
    prompt_meeting_msg = (
        f"The next step is to schedule a meeting. You can use:\n"
        f"\"Schedule meeting with {company_name} assigned to [Person Name] on [Date and Time]\""
    )
    response = send_message(reply_url, sender, prompt_meeting_msg)
    if source.lower() == "app":
        return response

    return {"status": "success", "message": "Qualification update handled"}