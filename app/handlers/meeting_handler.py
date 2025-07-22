#app/handlers/meeting_handler.py
import re
from datetime import datetime
from sqlalchemy.orm import Session
import dateparser
import logging
from app.models import Lead, Event
# --- MODIFIED: Import `update_lead_status` for automatic activity logging ---
from app.crud import get_lead_by_company, create_event, get_user_by_phone, get_user_by_name, update_lead_status
from app.schemas import EventCreate
from app.message_sender import send_message, format_phone,send_message
from app.temp_store import temp_store
from app.handlers.lead_handler import handle_update_lead
from app.gpt_parser import parse_update_fields, parse_core_lead_update
from app.handlers.qualification_handler import pending_context

logger = logging.getLogger(__name__)

# 🔹 Parse input message for scheduling
def extract_details_for_event(text: str):
    company_name, assigned_to, meeting_time_str = None, None, None
    match = re.search(
        r"schedule\s+meeting\s+with\s+(.+?)(?:\s+(?:for|assigned\s+to)\s+(.+?))?\s+(?:on|at)\s+(.+)",
        text, re.IGNORECASE
    )
    if match:
        company_name = match.group(1).strip()
        assigned_to = match.group(2).strip() if match.group(2) else None
        meeting_time_str = match.group(3).strip()
    return company_name, assigned_to, meeting_time_str

# ✅ Handle Meeting Scheduling
async def handle_meeting_schedule(db: Session, message_text: str, sender_phone: str, reply_url: str, source: str = "whatsapp"):
    try:
        company_name, assigned_to_name, meeting_time_str = extract_details_for_event(message_text)

        if not all([company_name, meeting_time_str]):
            error_msg = '⚠️ Invalid format. Use: "Schedule meeting with [Company] (assigned to [Person]) on [Date and Time]"'
            response = send_message(reply_url, sender_phone, error_msg, source)
            if source.lower() == "app":
                return response
            return {"status": "error", "message": "Invalid schedule format"}

        lead = get_lead_by_company(db, company_name)
        if not lead:
            response = send_message(reply_url, sender_phone, f"❌ Lead for '{company_name}' not found.", source)
            if source.lower() == "app":
                return response
            return {"status": "error", "message": "Lead not found"}

        if not assigned_to_name:
            assigned_to_name = lead.assigned_to
            logger.info(f"Assignee not specified, using existing assignee from lead: {assigned_to_name}")

        if not assigned_to_name:
            response = send_message(reply_url, sender_phone, f"❌ Could not find an assignee for '{company_name}'. Please specify one using '...assigned to [Person Name]...'")
            if source.lower() == "app":
                return response
            return {"status": "error", "message": "Assignee not found"}

        meeting_dt = dateparser.parse(meeting_time_str, settings={'PREFER_DATES_FROM': 'future'})
        if not meeting_dt:
            response = send_message(reply_url, sender_phone, f"❌ Could not understand the date/time: '{meeting_time_str}'", source)
            if source.lower() == "app":
                return response
            return {"status": "error", "message": "Invalid datetime"}

        event_data = EventCreate(
            lead_id=lead.id,
            assigned_to=assigned_to_name.title(),
            event_type="Meeting",
            event_time=meeting_dt,
            created_by=sender_phone,
            remark=f"Scheduled via WhatsApp by {sender_phone}"
        )

        new_event = create_event(db, event=event_data)
        logger.info(f"✅ Meeting event created with ID: {new_event.id} for lead: {lead.company_name}")

        confirmation = f"✅ Meeting scheduled for '{lead.company_name}' with {assigned_to_name.title()} on {meeting_dt.strftime('%A, %b %d at %I:%M %p')}."
        response = send_message(reply_url, sender_phone, confirmation, source)
        if source.lower() == "app":
            return response

        assigned_user = get_user_by_name(db, assigned_to_name)
        if assigned_user and assigned_user.usernumber and assigned_user.usernumber != sender_phone:
            notification_msg = (
                f"📢 A new meeting has been scheduled for you:\n"
                f"🏢 Company: *{lead.company_name}*\n"
                f"📅 Time: *{meeting_dt.strftime('%A, %b %d at %I:%M %p')}*"
            )
            response = send_message(reply_url, format_phone(assigned_user.usernumber), notification_msg, source)
            if source.lower() == "app":
                return response
            logger.info(f"✅ Sent meeting notification to assignee {assigned_to_name} at {assigned_user.usernumber}")

        return {"status": "success"}

    except Exception as e:
        logger.error(f"❌ Error in handle_meeting_schedule: {e}", exc_info=True)
        response = send_message(reply_url, sender_phone, "❌ An internal error occurred while scheduling the meeting.", source)
        if source.lower() == "app":
            return response
        return {"status": "error", "details": str(e)}

# --- This is the first step in the post-meeting flow ---
async def handle_post_meeting_update(db: Session, msg_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    company_name = extract_company_name_from_meeting_update(msg_text)
    remark = extract_remark_from_meeting_update(msg_text)

    if not company_name:
        response = send_message(reply_url, sender, "❌ Please specify which company the meeting was for. E.g., 'Meeting done for ABC Corp'", source)
        if source.lower() == "app": return response
        return {"status": "error", "message": "Company not found in message"}

    lead = get_lead_by_company(db, company_name)
    if not lead:
        response = send_message(reply_url, sender, f"❌ Lead not found for company: {company_name}", source)
        if source.lower() == "app": return response
        return {"status": "error", "message": "Company not found"}
 
    meeting_event = db.query(Event).filter(
        Event.lead_id == lead.id,
        Event.event_type.in_(["4 Phase Meeting", "Meeting"])
    ).order_by(Event.event_time.desc()).first()

    if not meeting_event:
        response = send_message(reply_url, sender, f"⚠️ No meeting found for {company_name}", source)
        if source.lower() == "app": return response
        return {"status": "error", "message": "No meeting found"}

    meeting_event.phase = "Done"
    db.commit() # Commit the change to the meeting event phase first.

    # --- MODIFIED: Use centralized function to update status and log activity ---
    update_lead_status(
        db, 
        lead_id=lead.id, 
        status="Meeting Done", 
        updated_by=sender, 
        remark=remark if remark != "No remark provided." else "Meeting completed."
    )

    send_message(reply_url, sender, f"✅ Meeting marked done for *{company_name}*.", source)

    # Ask the user if they want to change core details
    ask_msg = f"Do you need to update the core details for this lead (e.g., Company Name, Contact)?\n\nPlease reply with *Yes* or *No*."
    send_message(reply_url, sender, ask_msg, source)

    # Set context for the next step
    pending_context[sender] = {"intent": "awaiting_details_change_decision", "company_name": company_name}
    logger.info(f"Set context for {sender} to 'awaiting_details_change_decision' for company '{company_name}'")

    return {"status": "success", "message": "Meeting marked done, awaiting core detail change decision."}


# --- NEW HANDLER FUNCTION for Yes/No decision ---
async def handle_details_change_decision(db: Session, msg_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    context = pending_context.get(sender)
    if not context or context.get("intent") != "awaiting_details_change_decision":
        response = send_message(reply_url, sender, "Sorry, I lost the context. How can I help?", source)
        if source.lower() == "app": return response
        return {"status": "error", "message": "Context not found"}

    company_name = context["company_name"]
    pending_context.pop(sender, None)  # Clean up context

    positive_keywords = ["yes", "y", "ok", "okay", "sure", "do it"]
    if any(keyword in msg_text.lower().strip() for keyword in positive_keywords):
        # User wants to update core details
        ask_msg = "👍 Please provide the new details. For example:\n`Company Name: New XYZ Corp, Contact: Sunita, Phone: 9876543210`"
        send_message(reply_url, sender, ask_msg, source)
        pending_context[sender] = {"intent": "awaiting_core_lead_update", "company_name": company_name}
        logger.info(f"Set context for {sender} to 'awaiting_core_lead_update' for company '{company_name}'")
    else:
        # User does not want to update, proceed to ask for other missing fields
        logger.info(f"User chose not to update core details for {company_name}. Checking for other missing fields.")
        await _ask_for_remaining_fields(db, sender, company_name, reply_url, source)
        
    return {"status": "success"}


# --- NEW HANDLER FUNCTION for updating core details ---
async def handle_core_lead_update(db: Session, msg_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    context = pending_context.get(sender)
    if not context or context.get("intent") != "awaiting_core_lead_update":
        response = send_message(reply_url, sender, "Sorry, I lost the context. How can I help?", source)
        if source.lower() == "app": return response
        return {"status": "error", "message": "Context not found"}

    original_company_name = context["company_name"]
    pending_context.pop(sender, None)  # Clean up context

    lead = get_lead_by_company(db, original_company_name)
    if not lead:
        response = send_message(reply_url, sender, f"❌ Strange, I can no longer find the lead for {original_company_name}.", source)
        if source.lower() == "app": return response
        return {"status": "error", "message": "Lead not found"}

    update_data, _ = parse_core_lead_update(msg_text)
    
    if not update_data:
        send_message(reply_url, sender, "⚠️ I couldn't find any core details to update. Let's proceed.", source)
    else:
        updated_fields_list = []
        for field, value in update_data.items():
            if hasattr(lead, field) and value:
                setattr(lead, field, value)
                updated_fields_list.append(field.replace('_', ' ').title())
        db.commit()
        db.refresh(lead)
        send_message(reply_url, sender, f"✅ Got it. Updated core details for '{lead.company_name}': {', '.join(updated_fields_list)}.", source)

    # Now, check for other missing fields
    await _ask_for_remaining_fields(db, sender, lead.company_name, reply_url, source)

    return {"status": "success", "message": "Core lead details updated."}


# --- NEW HELPER FUNCTION to check remaining fields and prompt for demo ---
async def _ask_for_remaining_fields(db: Session, sender: str, company_name: str, reply_url: str, source: str):
    lead = get_lead_by_company(db, company_name)
    if not lead:
        return # Should not happen, but good practice

    missing_fields = []
    if not lead.segment: missing_fields.append("Segment")
    if not lead.team_size: missing_fields.append("Team Size")
    if not lead.phone_2: missing_fields.append("Alternate Phone (phone_2)")
    if not lead.turnover: missing_fields.append("Turnover")
    if not lead.current_system: missing_fields.append("Current System")
    if not lead.machine_specification: missing_fields.append("Machine Specification")
    if not lead.challenges: missing_fields.append("Challenges")

    if missing_fields:
        ask_msg = (
            f"📝 Please provide any of the following missing details for *{company_name}*:\n👉 " +
            ", ".join(missing_fields) +
            "\n\n(Reply with details or type 'skip')"
        )
        send_message(reply_url, sender, ask_msg, source)
        pending_context[sender] = {"intent": "awaiting_meeting_details", "company_name": company_name}
        logger.info(f"Set context for {sender} to 'awaiting_meeting_details' to capture remaining fields for '{company_name}'")
    else:
        # If nothing is missing, go straight to scheduling a demo
        prompt_demo_msg = (
            f"👍 All details for *{company_name}* are complete.\n\nThe next step is to schedule a demo. You can use:\n"
            f"\"Schedule demo for {company_name} on [Date and Time]\""
        )
        send_message(reply_url, sender, prompt_demo_msg, source)

# --- This function now handles the final update step ---
async def handle_meeting_details_update(db: Session, msg_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    """Handles the user's reply with the remaining optional details."""
    context = pending_context.get(sender)
    if not context or context.get("intent") != "awaiting_meeting_details":
        response = send_message(reply_url, sender, "Sorry, I lost the context. How can I help?", source)
        if source.lower() == "app": return response
        return {"status": "error", "message": "Context not found"}

    company_name = context["company_name"]
    pending_context.pop(sender, None)

    if "skip" in msg_text.lower():
        send_message(reply_url, sender, f"👍 Understood. Skipping additional details for now.", source)
    else:
        lead = get_lead_by_company(db, company_name)
        if not lead:
            response = send_message(reply_url, sender, f"❌ Strange, I can no longer find the lead for {company_name}.", source)
            if source.lower() == "app": return response
            return {"status": "error", "message": "Lead not found"}
            
        update_fields, _ = parse_update_fields(msg_text)
        
        if not update_fields and "skip" not in msg_text.lower():
            update_fields['remark'] = msg_text.strip()
            logger.info(f"No specific fields found. Treating entire message as remark for {company_name}")

        updated_fields_list = []
        for field, value in update_fields.items():
            if hasattr(lead, field) and value:
                if field == 'remark' and lead.remark:
                    setattr(lead, field, f"{lead.remark}\n--\n{value}")
                else:
                    setattr(lead, field, value)
                updated_fields_list.append(field.replace('_', ' ').title())

        if not updated_fields_list:
            send_message(reply_url, sender, "⚠️ I couldn't find any details to update. Let's move on for now.", source)
        else:
            db.commit()
            send_message(reply_url, sender, f"✅ Got it. Updated details for '{company_name}': {', '.join(updated_fields_list)}.", source)

    # In all cases, prompt for the demo
    prompt_demo_msg = (
        f"The next step is to schedule a demo for *{company_name}*. You can use:\n"
        f"\"Schedule demo for {company_name} on [Date and Time]\""
    )
    send_message(reply_url, sender, prompt_demo_msg, source)

    return {"status": "success", "message": "Meeting details updated, prompted for demo."}


# ✅ Reschedule Meeting (Unchanged)
async def handle_reschedule_meeting(db: Session, msg_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    try:
        match = re.search(r"reschedule\s+meeting\s+for\s+(.+?)\s+on\s+(.+)", msg_text, re.IGNORECASE)
        if not match:
            response = send_message(reply_url, sender,
                "⚠️ Invalid format. Use: 'Reschedule meeting for [Company Name] on [Date and Time]'", source)
            if source.lower() == "app":
                return response
            return {"status": "error", "message": "Invalid reschedule format"}

        company_name = match.group(1).strip()
        new_time_str = match.group(2).strip()

        new_datetime = dateparser.parse(new_time_str, settings={'PREFER_DATES_FROM': 'future'})
        if not new_datetime:
            response = send_message(reply_url, sender,
                f"❌ Couldn't parse new meeting time: '{new_time_str}'", source)
            if source.lower() == "app":
                return response
            return {"status": "error", "message": "Invalid datetime"}

        lead = get_lead_by_company(db, company_name)
        if not lead:
            response = send_message(reply_url, sender,
                f"❌ Lead not found for company: {company_name}", source)
            if source.lower() == "app":
                return response
            return {"status": "error", "message": "Company not found"}

        event = db.query(Event).filter(
            Event.lead_id == lead.id,
            Event.event_type.in_(["4 Phase Meeting","Meeting"])
        ).order_by(Event.event_time.desc()).first()

        if not event:
            response = send_message(reply_url, sender,
                f"⚠️ No existing meeting found for {company_name}", source)
            if source.lower() == "app":
                return response
            return {"status": "error", "message": "No existing meeting"}

        event.event_time = new_datetime
        event.remark = f"Rescheduled via WhatsApp by {sender}"

        if hasattr(event, "updated_at"):
            event.updated_at = datetime.now()

        db.commit()

        response = send_message(reply_url, sender,
            f"✅ Meeting for *{company_name}* rescheduled to {new_datetime.strftime('%d %b %Y at %I:%M %p')}.", source)
        if source.lower() == "app":
            return response

        if event.assigned_to:
            assigned_user = get_user_by_name(db, event.assigned_to)
            if assigned_user and assigned_user.usernumber and assigned_user.usernumber != sender:
                response = send_message(reply_url, format_phone(assigned_user.usernumber),
                    f"📢 Meeting for *{company_name}* has been rescheduled.\n📅 New Time: {new_datetime.strftime('%d %b %Y at %I:%M %p')}", source)
                if source.lower() == "app":
                    return response
                logger.info(f"✅ Sent reschedule notification to assignee {assigned_user.username} at {assigned_user.usernumber}")

        return {"status": "success"}

    except Exception as e:
        logging.exception("❌ Exception during meeting reschedule")
        response = send_message(reply_url, sender, "❌ Internal error while rescheduling meeting.", source)
        if source.lower() == "app":
            return response
        return {"status": "error", "details": str(e)}

# 🔎 Extractors
def extract_company_name_from_meeting_update(msg_text: str) -> str:
    match = re.search(r"meeting done for (.+?)(?:\.|,| is| they|$)", msg_text, re.IGNORECASE)
    return match.group(1).strip() if match else ""

def extract_remark_from_meeting_update(msg_text: str) -> str:
    match = re.search(r"(they .*|remark[:\-]?\s*.+)", msg_text, re.IGNORECASE)
    return match.group(1).strip().lstrip("Remark:").strip() if match else "No remark provided."