# app/handlers/meeting_handler.py
import re
from datetime import datetime
from sqlalchemy.orm import Session
import dateparser
import logging
from app.models import Lead, Event
from app.crud import get_lead_by_company, create_event, get_user_by_phone, get_user_by_name, update_lead_status, create_activity_log
from app.schemas import EventCreate, ActivityLogCreate
from app.message_sender import send_message, format_phone, send_whatsapp_message
from app.temp_store import temp_store
from app.handlers.lead_handler import handle_update_lead
from app.gpt_parser import parse_update_fields, parse_core_lead_update
from app.handlers.qualification_handler import pending_context

logger = logging.getLogger(__name__)

def extract_details_for_event(text: str):
    company_name, assigned_to, meeting_time_str = None, None, None
    match = re.search(
        r"schedule\s+meeting\s+with\s+(.+?)\s+(?:on|at)\s+(.+?)(?:\s+assigned\s+to\s+(.+))?$",
        text, re.IGNORECASE
    )
    if match:
        company_name = match.group(1).strip()
        meeting_time_str = match.group(2).strip()
        assigned_to = match.group(3).strip() if match.group(3) else None
    return company_name, assigned_to, meeting_time_str

async def handle_meeting_schedule(db: Session, message_text: str, sender_phone: str, reply_url: str, source: str = "whatsapp"):
    try:
        company_name, assigned_to_name, meeting_time_str = extract_details_for_event(message_text)

        if not all([company_name, meeting_time_str]):
            error_msg = '⚠️ Invalid format. Use: "Schedule meeting with [Company] on [Date and Time] (assigned to [Person])"'
            return send_message(reply_url, sender_phone, error_msg, source)

        lead = get_lead_by_company(db, company_name)
        if not lead:
            return send_message(reply_url, sender_phone, f"❌ Lead for '{company_name}' not found.", source)

        if not assigned_to_name:
            assigned_to_name = lead.assigned_to
            logger.info(f"Assignee not specified, using existing assignee from lead: {assigned_to_name}")

        user_for_assignment = get_user_by_name(db, assigned_to_name)
        if not user_for_assignment:
            return send_message(reply_url, sender_phone, f"❌ Could not find an assignee named '{assigned_to_name}'. Please specify a valid user.", source)

        meeting_dt = dateparser.parse(meeting_time_str, settings={'PREFER_DATES_FROM': 'future', 'DATE_ORDER': 'DMY'})
        if not meeting_dt:
            return send_message(reply_url, sender_phone, f"❌ Could not understand the date/time: '{meeting_time_str}'", source)

        event_data = EventCreate(
            lead_id=lead.id,
            assigned_to=user_for_assignment.username,
            event_type="Meeting",
            event_time=meeting_dt,
            created_by=sender_phone,
            remark=f"Scheduled via {source} by {sender_phone}"
        )
        new_event = create_event(db, event=event_data)
        logger.info(f"✅ Meeting event created with ID: {new_event.id} for lead: {lead.company_name}")

        # --- REVISED NOTIFICATION AND RESPONSE LOGIC ---
        # 1. Notify assignee independently (works for app and WhatsApp)
        if user_for_assignment and user_for_assignment.usernumber and user_for_assignment.usernumber != sender_phone:
            notification_msg = (
                f"📢 A new meeting has been scheduled for you:\n"
                f"🏢 Company: *{lead.company_name}*\n"
                f"📅 Time: *{meeting_dt.strftime('%A, %b %d at %I:%M %p')}*"
            )
            send_whatsapp_message(reply_url, format_phone(user_for_assignment.usernumber), notification_msg)
            logger.info(f"✅ Sent meeting notification to assignee {user_for_assignment.username} at {user_for_assignment.usernumber}")

        # 2. Send confirmation to the original user (app or WhatsApp)
        confirmation = f"✅ Meeting scheduled for '{lead.company_name}' with {user_for_assignment.username} on {meeting_dt.strftime('%A, %b %d at %I:%M %p')}."
        return send_message(reply_url, sender_phone, confirmation, source)

    except Exception as e:
        logger.error(f"❌ Error in handle_meeting_schedule: {e}", exc_info=True)
        return send_message(reply_url, sender_phone, "❌ An internal error occurred while scheduling the meeting.", source)

async def handle_post_meeting_update(db: Session, msg_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    company_name = extract_company_name_from_meeting_update(msg_text)
    remark = extract_remark_from_meeting_update(msg_text)

    if not company_name:
        return send_message(reply_url, sender, "❌ Please specify which company the meeting was for. E.g., 'Meeting done for ABC Corp'", source)

    lead = get_lead_by_company(db, company_name)
    if not lead:
        return send_message(reply_url, sender, f"❌ Lead not found for company: {company_name}", source)
 
    meeting_event = db.query(Event).filter(Event.lead_id == lead.id, Event.event_type.in_(["4 Phase Meeting", "Meeting"])).order_by(Event.event_time.desc()).first()
    if not meeting_event:
        return send_message(reply_url, sender, f"⚠️ No meeting found for {company_name}", source)

    meeting_event.phase = "Done"
    db.commit()

    update_lead_status(db, lead_id=lead.id, status="Meeting Done", updated_by=sender, remark=remark if remark != "No remark provided." else "Meeting completed.")

    # --- REVISED RESPONSE LOGIC ---
    reply_parts = [
        f"✅ Meeting marked done for *{company_name}*.",
        "Do you need to update the core details for this lead (e.g., Company Name, Contact)?\n\nPlease reply with *Yes* or *No*."
    ]
    final_reply = "\n\n".join(reply_parts)

    pending_context[sender] = {"intent": "awaiting_details_change_decision", "company_name": company_name}
    logger.info(f"Set context for {sender} to 'awaiting_details_change_decision' for company '{company_name}'")

    return send_message(reply_url, sender, final_reply, source)

async def handle_details_change_decision(db: Session, msg_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    context = pending_context.get(sender)
    if not context or context.get("intent") != "awaiting_details_change_decision":
        return send_message(reply_url, sender, "Sorry, I lost the context. How can I help?", source)

    company_name = context["company_name"]
    pending_context.pop(sender, None)

    positive_keywords = ["yes", "y", "ok", "okay", "sure", "do it"]
    if any(keyword in msg_text.lower().strip() for keyword in positive_keywords):
        ask_msg = "👍 Please provide the new details. For example:\n`Company Name: New XYZ Corp, Contact: Sunita, Phone: 9876543210`"
        pending_context[sender] = {"intent": "awaiting_core_lead_update", "company_name": company_name}
        logger.info(f"Set context for {sender} to 'awaiting_core_lead_update' for company '{company_name}'")
        return send_message(reply_url, sender, ask_msg, source)
    else:
        logger.info(f"User chose not to update core details for {company_name}. Checking for other missing fields.")
        prompt_message, next_intent = _get_post_update_prompt(db, company_name)
        if next_intent:
            pending_context[sender] = {"intent": next_intent, "company_name": company_name}
        return send_message(reply_url, sender, prompt_message, source)

async def handle_core_lead_update(db: Session, msg_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    context = pending_context.get(sender)
    if not context or context.get("intent") != "awaiting_core_lead_update":
        return send_message(reply_url, sender, "Sorry, I lost the context. How can I help?", source)

    original_company_name = context["company_name"]
    pending_context.pop(sender, None)

    lead = get_lead_by_company(db, original_company_name)
    if not lead:
        return send_message(reply_url, sender, f"❌ Strange, I can no longer find the lead for {original_company_name}.", source)

    update_data, _ = parse_core_lead_update(msg_text)
    reply_parts = []
    
    if not update_data:
        reply_parts.append("⚠️ I couldn't find any core details to update. Let's proceed.")
    else:
        updated_fields_list = []
        for field, value in update_data.items():
            if hasattr(lead, field) and value:
                setattr(lead, field, value)
                updated_fields_list.append(field.replace('_', ' ').title())
        db.commit()
        db.refresh(lead)
        reply_parts.append(f"✅ Got it. Updated core details for '{lead.company_name}': {', '.join(updated_fields_list)}.")

    prompt_message, next_intent = _get_post_update_prompt(db, lead.company_name)
    reply_parts.append(prompt_message)
    if next_intent:
        pending_context[sender] = {"intent": next_intent, "company_name": lead.company_name}
        
    final_reply = "\n\n".join(reply_parts)
    return send_message(reply_url, sender, final_reply, source)

def _get_post_update_prompt(db: Session, company_name: str) -> (str, str or None):
    """
    Helper to generate the next prompt after a meeting update, checking for missing fields.
    Returns the message string and the next context intent, if any.
    """
    lead = get_lead_by_company(db, company_name)
    if not lead:
        return "An unexpected error occurred.", None

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
        return ask_msg, "awaiting_meeting_details"
    else:
        prompt_demo_msg = (
            f"👍 All details for *{company_name}* are complete.\n\nThe next step is to schedule a demo. You can use:\n"
            f"\"Schedule demo for {company_name} on [Date and Time]\""
        )
        return prompt_demo_msg, None

async def handle_meeting_details_update(db: Session, msg_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    context = pending_context.get(sender)
    if not context or context.get("intent") != "awaiting_meeting_details":
        return send_message(reply_url, sender, "Sorry, I lost the context. How can I help?", source)

    company_name = context["company_name"]
    pending_context.pop(sender, None)

    reply_parts = []
    if "skip" in msg_text.lower():
        reply_parts.append("👍 Understood. Skipping additional details for now.")
    else:
        lead = get_lead_by_company(db, company_name)
        if not lead:
            return send_message(reply_url, sender, f"❌ Strange, I can no longer find the lead for {company_name}.", source)
            
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
            reply_parts.append("⚠️ I couldn't find any details to update. Let's move on for now.")
        else:
            db.commit()
            reply_parts.append(f"✅ Got it. Updated details for '{company_name}': {', '.join(updated_fields_list)}.")

    prompt_demo_msg = (
        f"The next step is to schedule a demo for *{company_name}*. You can use:\n"
        f"\"Schedule demo for {company_name} on [Date and Time]\""
    )
    reply_parts.append(prompt_demo_msg)
    final_reply = "\n\n".join(reply_parts)
    
    return send_message(reply_url, sender, final_reply, source)

async def handle_reschedule_meeting(db: Session, msg_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    try:
        match = re.search(r"reschedule\s+meeting\s+for\s+(.+?)\s+on\s+(.+)", msg_text, re.IGNORECASE)
        if not match:
            return send_message(reply_url, sender, "⚠️ Invalid format. Use: 'Reschedule meeting for [Company Name] on [Date and Time]'", source)

        company_name, new_time_str = match.group(1).strip(), match.group(2).strip()
        new_datetime = dateparser.parse(new_time_str, settings={'PREFER_DATES_FROM': 'future'})
        if not new_datetime:
            return send_message(reply_url, sender, f"❌ Couldn't parse new meeting time: '{new_time_str}'", source)

        lead = get_lead_by_company(db, company_name)
        if not lead:
            return send_message(reply_url, sender, f"❌ Lead not found for company: {company_name}", source)

        event = db.query(Event).filter(Event.lead_id == lead.id, Event.event_type.in_(["4 Phase Meeting","Meeting"])).order_by(Event.event_time.desc()).first()
        if not event:
            return send_message(reply_url, sender, f"⚠️ No existing meeting found for {company_name}", source)
        
        old_time = event.event_time.strftime('%d %b %Y at %I:%M %p')
        new_time_formatted = new_datetime.strftime('%d %b %Y at %I:%M %p')

        event.event_time = new_datetime
        event.remark = f"Rescheduled via {source} by {sender}"
        db.commit()

        activity_details = f"Meeting rescheduled from {old_time} to {new_time_formatted} by {sender}."
        create_activity_log(db, activity=ActivityLogCreate(lead_id=lead.id, phase=lead.status, details=activity_details))

        # Notify assignee independently
        if event.assigned_to:
            assigned_user = get_user_by_name(db, event.assigned_to)
            if assigned_user and assigned_user.usernumber and assigned_user.usernumber != sender:
                notification = f"📢 Meeting for *{company_name}* has been rescheduled.\n📅 New Time: {new_time_formatted}"
                send_whatsapp_message(reply_url, format_phone(assigned_user.usernumber), notification)
                logger.info(f"✅ Sent reschedule notification to assignee {assigned_user.username} at {assigned_user.usernumber}")

        # Send confirmation to original user
        confirmation = f"✅ Meeting for *{company_name}* rescheduled to {new_time_formatted}."
        return send_message(reply_url, sender, confirmation, source)

    except Exception as e:
        logging.exception("❌ Exception during meeting reschedule")
        return send_message(reply_url, sender, "❌ Internal error while rescheduling meeting.", source)

def extract_company_name_from_meeting_update(msg_text: str) -> str:
    match = re.search(r"meeting done for (.+?)(?:\.|,| is| they|$)", msg_text, re.IGNORECASE)
    return match.group(1).strip() if match else ""

def extract_remark_from_meeting_update(msg_text: str) -> str:
    match = re.search(r"(they .*|remark[:\-]?\s*.+)", msg_text, re.IGNORECASE)
    return match.group(1).strip().lstrip("Remark:").strip() if match else "No remark provided."