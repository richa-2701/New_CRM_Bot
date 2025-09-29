# app/handlers/meeting_handler.py
import re
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import dateparser
import logging
import pytz

from app.models import Lead, Event, Demo, Reminder
from app.crud import get_lead_by_company, create_event, get_user_by_phone, get_user_by_name, update_lead_status, create_activity_log, is_user_available, create_reminder
from app.schemas import EventCreate, ActivityLogCreate, ReminderCreate
from app.message_sender import send_message, format_phone, send_whatsapp_message
from app.temp_store import temp_store
from app.handlers.lead_handler import handle_update_lead
from app.gpt_parser import parse_update_fields, parse_core_lead_update
from app.handlers.qualification_handler import pending_context

logger = logging.getLogger(__name__)

MEETING_DEFAULT_DURATION_MINUTES = 20

LOCAL_TIMEZONE = pytz.timezone('Asia/Kolkata')
UTC = pytz.utc


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
            return send_message(number=sender_phone, message=error_msg, source=source)

        lead = get_lead_by_company(db, company_name)
        if not lead:
            return send_message(number=sender_phone, message=f"❌ Lead for '{company_name}' not found.", source=source)

        if not assigned_to_name:
            assigned_to_name = lead.assigned_to
            logger.info(f"Assignee not specified, using existing assignee from lead: {assigned_to_name}")

        user_for_assignment = get_user_by_name(db, assigned_to_name)
        if not user_for_assignment:
            return send_message(number=sender_phone, message=f"❌ Could not find an assignee named '{assigned_to_name}'. Please specify a valid user.", source=source)

        meeting_dt_naive = dateparser.parse(meeting_time_str, settings={'DATE_ORDER': 'DMY', 'PREFER_DATES_FROM': 'future'})
        if not meeting_dt_naive:
            return send_message(number=sender_phone, message=f"❌ Could not understand the date/time: '{meeting_time_str}'", source=source)

        meeting_dt_local = LOCAL_TIMEZONE.localize(meeting_dt_naive)
        meeting_dt_utc = meeting_dt_local.astimezone(UTC)
        meeting_start_utc_naive = meeting_dt_utc.replace(tzinfo=None)
        meeting_end_utc_naive = meeting_start_utc_naive + timedelta(minutes=MEETING_DEFAULT_DURATION_MINUTES)

        if meeting_start_utc_naive < datetime.utcnow():
            error_msg = f"❌ The date and time you entered ({meeting_dt_local.strftime('%d-%b-%Y %I:%M %p')}) is in the past. Please provide a future date and time."
            return send_message(number=sender_phone, message=error_msg, source=source)

        conflict = is_user_available(db, user_for_assignment.username, user_for_assignment.usernumber, meeting_start_utc_naive, meeting_end_utc_naive)
        if conflict:
            conflict_type = "Meeting" if isinstance(conflict, Event) else "Demo"
            conflict_lead = db.query(Lead).filter(Lead.id == conflict.lead_id).first()
            conflict_lead_name = conflict_lead.company_name if conflict_lead else "another task"
            conflict_start_utc = conflict.event_time if isinstance(conflict, Event) else conflict.start_time
            conflict_start_local = UTC.localize(conflict_start_utc).astimezone(LOCAL_TIMEZONE)

            error_msg = (
                f"❌ Scheduling failed. *{user_for_assignment.username}* is already booked at that time.\n\n"
                f"Conflict: {conflict_type} with *{conflict_lead_name}*\n"
                f"Time: {conflict_start_local.strftime('%I:%M %p')}"
            )
            return send_message(number=sender_phone, message=error_msg, source=source)

        sender_user = get_user_by_phone(db, sender_phone)
        sender_name = sender_user.username if sender_user else sender_phone

        event_data = EventCreate(
            lead_id=lead.id,
            assigned_to=user_for_assignment.username,
            event_type="Meeting",
            event_time=meeting_start_utc_naive,
            event_end_time=meeting_end_utc_naive,
            created_by=sender_name,
            remark=f"Scheduled via {source} by {sender_name}"
        )
        new_event = create_event(db, event=event_data)
        update_lead_status(db, lead.id, "Meeting Scheduled", updated_by=sender_name)
        logger.info(f"✅ Meeting event created with ID: {new_event.id} for lead: {lead.company_name}")

        time_formatted_local = meeting_dt_local.strftime('%A, %b %d at %I:%M %p')
        reminder_message = f"You have a meeting scheduled for *{lead.company_name}* on {time_formatted_local}."

        one_day_before = new_event.event_time - timedelta(days=1)
        if one_day_before > datetime.utcnow():
            create_reminder(db, ReminderCreate(
                lead_id=lead.id, user_id=user_for_assignment.id, assigned_to=user_for_assignment.username,
                remind_time=one_day_before, message=f"(1 day away) {reminder_message}", is_hidden_from_activity_log=True
            ))

        one_hour_before = new_event.event_time - timedelta(hours=1)
        if one_hour_before > datetime.utcnow():
            create_reminder(db, ReminderCreate(
                lead_id=lead.id, user_id=user_for_assignment.id, assigned_to=user_for_assignment.username,
                remind_time=one_hour_before, message=f"(in 1 hour) {reminder_message}", is_hidden_from_activity_log=True
            ))
        
        logger.info(f"Scheduled pre-meeting reminders for event ID {new_event.id}")
        
        # --- START: CORRECTED NOTIFICATION LOGIC ---
        # The assignee should always be notified if they have a WhatsApp number.
        if user_for_assignment and user_for_assignment.usernumber:
            is_self_notification = (sender_phone == user_for_assignment.usernumber)
            
            if is_self_notification:
                # Formulate a message for someone scheduling for themselves
                notification_msg = (
                    f"✅ This is a confirmation for the meeting you scheduled:\n\n"
                    f"🏢 Company: *{lead.company_name}*\n"
                    f"📅 Time: *{time_formatted_local}*"
                )
            else:
                contact_name_for_msg = lead.contacts[0].contact_name if lead.contacts and lead.contacts[0].contact_name else 'N/A'
                contact_phone_for_msg = lead.contacts[0].phone if lead.contacts and lead.contacts[0].phone else 'N/A'

                # Formulate a message for someone else scheduling for the assignee
                notification_msg = (
                    f"📢 A new meeting has been scheduled for you by *{sender_name}*:\n\n"
                    f"🏢 Company: *{lead.company_name}*\n"
                    f"👤 Contact: {contact_name_for_msg} ({contact_phone_for_msg})\n"
                    f"📅 Time: *{time_formatted_local}*"
                )
            
            send_whatsapp_message(number=format_phone(user_for_assignment.usernumber), message=notification_msg)
            logger.info(f"✅ Sent meeting notification to assignee {user_for_assignment.username} at {user_for_assignment.usernumber}")
        # --- END: CORRECTED NOTIFICATION LOGIC ---

        # The confirmation to the person who sent the command remains the same
        confirmation = f"✅ Meeting scheduled for '{lead.company_name}' with {user_for_assignment.username} on {time_formatted_local}. Reminders have been set."
        return send_message(number=sender_phone, message=confirmation, source=source)

    except Exception as e:
        logger.error(f"❌ Error in handle_meeting_schedule: {e}", exc_info=True)
        return send_message(number=sender_phone, message="❌ An internal error occurred while scheduling the meeting.", source=source)

async def handle_reschedule_meeting(db: Session, msg_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    try:
        match = re.search(r"reschedule\s+meeting\s+for\s+(.+?)\s+on\s+(.+?)(?:\s+(?:assigned\s+to|to)\s+(.+))?$", msg_text, re.IGNORECASE)
        if not match:
            return send_message(number=sender, message="⚠️ Invalid format. Use: 'Reschedule meeting for [Company] on [Date] to [New Assignee]'", source=source)

        company_name = match.group(1).strip()
        new_time_str = match.group(2).strip()
        new_assignee_name = match.group(3).strip() if match.group(3) else None

        new_datetime_naive = dateparser.parse(new_time_str, settings={'DATE_ORDER': 'DMY', 'PREFER_DATES_FROM': 'future'})
        if not new_datetime_naive:
            return send_message(number=sender, message=f"❌ Couldn't parse new meeting time: '{new_time_str}'", source=source)
        
        new_datetime_local = LOCAL_TIMEZONE.localize(new_datetime_naive)
        new_datetime_utc = new_datetime_local.astimezone(UTC)
        new_start_utc_naive = new_datetime_utc.replace(tzinfo=None)
        new_end_utc_naive = new_start_utc_naive + timedelta(minutes=MEETING_DEFAULT_DURATION_MINUTES)

        if new_start_utc_naive < datetime.utcnow():
            error_msg = f"❌ The new date and time you entered ({new_datetime_local.strftime('%d-%b-%Y %I:%M %p')}) is in the past. Please provide a future date and time."
            return send_message(number=sender, message=error_msg, source=source)

        lead = get_lead_by_company(db, company_name)
        if not lead:
            return send_message(number=sender, message=f"❌ Lead not found for company: {company_name}", source=source)

        event = db.query(Event).filter(Event.lead_id == lead.id, Event.event_type.in_(["4 Phase Meeting","Meeting"])).order_by(Event.event_time.desc()).first()
        if not event:
            return send_message(number=sender, message=f"⚠️ No existing meeting found for {company_name}", source=source)
        
        final_assignee_user = None
        if new_assignee_name:
            lookup_user = get_user_by_name(db, new_assignee_name) or get_user_by_phone(db, new_assignee_name)
            if not lookup_user:
                return send_message(number=sender, message=f"❌ Could not find the new assignee: '{new_assignee_name}'", source=source)
            final_assignee_user = lookup_user
        else:
            lookup_user = get_user_by_name(db, event.assigned_to)
            if not lookup_user:
                logger.error(f"Critical error: Could not find original assignee '{event.assigned_to}' for event ID {event.id}")
                return send_message(number=sender, message="❌ Internal error: Could not verify the original assignee.", source=source)
            final_assignee_user = lookup_user
        
        conflict = is_user_available(db, final_assignee_user.username, final_assignee_user.usernumber, new_start_utc_naive, new_end_utc_naive, exclude_event_id=event.id)
        if conflict:
            conflict_type = "Meeting" if isinstance(conflict, Event) else "Demo"
            conflict_lead = db.query(Lead).filter(Lead.id == conflict.lead_id).first()
            conflict_lead_name = conflict_lead.company_name if conflict_lead else "another task"
            conflict_start_utc = conflict.event_time if isinstance(conflict, Event) else conflict.start_time
            conflict_start_local = UTC.localize(conflict_start_utc).astimezone(LOCAL_TIMEZONE)
            
            error_msg = (
                f"❌ Rescheduling failed. *{final_assignee_user.username}* is already booked at that time.\n\n"
                f"Conflict: {conflict_type} with *{conflict_lead_name}*\n"
                f"Time: {conflict_start_local.strftime('%I:%M %p')}"
            )
            return send_message(number=sender, message=error_msg, source=source)
        
        db.query(Reminder).filter(Reminder.lead_id == lead.id, Reminder.message.like(f"%meeting scheduled for *{lead.company_name}*%")).delete(synchronize_session=False)
        
        time_formatted_local = new_datetime_local.strftime('%A, %b %d at %I:%M %p')
        reminder_message = f"You have a meeting scheduled for *{lead.company_name}* on {time_formatted_local}."

        one_day_before = new_start_utc_naive - timedelta(days=1)
        if one_day_before > datetime.utcnow():
            create_reminder(db, ReminderCreate(
                lead_id=lead.id, user_id=final_assignee_user.id, assigned_to=final_assignee_user.username,
                remind_time=one_day_before, message=f" (1 day away) {reminder_message}", is_hidden_from_activity_log=True
            ))

        one_hour_before = new_start_utc_naive - timedelta(hours=1)
        if one_hour_before > datetime.utcnow():
            create_reminder(db, ReminderCreate(
                lead_id=lead.id, user_id=final_assignee_user.id, assigned_to=final_assignee_user.username,
                remind_time=one_hour_before, message=f" (in 1 hour) {reminder_message}", is_hidden_from_activity_log=True
            ))
        
        logger.info(f"Re-scheduled pre-meeting reminders for event ID {event.id} for user {final_assignee_user.username}")
        
        old_time_local = UTC.localize(event.event_time).astimezone(LOCAL_TIMEZONE)
        old_time_str = old_time_local.strftime('%d %b %Y at %I:%M %p')

        sender_user = get_user_by_phone(db, sender)
        sender_name = sender_user.username if sender_user else sender

        event.event_time = new_start_utc_naive
        event.event_end_time = new_end_utc_naive
        event.assigned_to = final_assignee_user.username
        event.remark = f"Rescheduled via {source} by {sender_name}"
        event.created_by = sender_name
        db.commit()

        activity_details = f"Meeting rescheduled from {old_time_str} to {time_formatted_local} by {sender_name}."
        if new_assignee_name:
            activity_details += f" New assignee is {final_assignee_user.username}."
        create_activity_log(db, activity=ActivityLogCreate(lead_id=lead.id, phase=lead.status, details=activity_details))

        # --- START: CORRECTED NOTIFICATION LOGIC FOR RESCHEDULE ---
        if final_assignee_user.usernumber:
            is_self_notification = (sender == final_assignee_user.usernumber)

            if is_self_notification:
                notification = f"✅ This is a confirmation for the meeting you rescheduled for *{company_name}*.\n📅 New Time: {time_formatted_local}"
            else:
                 notification = f"📢 Meeting for *{company_name}* has been rescheduled for you by *{sender_name}*.\n📅 New Time: {time_formatted_local}"

            send_whatsapp_message(number=format_phone(final_assignee_user.usernumber), message=notification)
            logger.info(f"✅ Sent reschedule notification to assignee {final_assignee_user.username} at {final_assignee_user.usernumber}")
        # --- END: CORRECTED NOTIFICATION LOGIC FOR RESCHEDULE ---

        confirmation = f"✅ Meeting for *{company_name}* rescheduled to {time_formatted_local}. Reminders have been updated."
        if new_assignee_name:
            confirmation += f"\n👤 It is now assigned to: {final_assignee_user.username}"
        
        return send_message(number=sender, message=confirmation, source=source)

    except Exception as e:
        logging.exception("❌ Exception during meeting reschedule")
        db.rollback()
        return send_message(number=sender, message="❌ Internal error while rescheduling meeting.", source=source)

async def handle_post_meeting_update(db: Session, msg_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    company_name = extract_company_name_from_meeting_update(msg_text)
    remark = extract_remark_from_meeting_update(msg_text)

    if not company_name:
        return send_message(number=sender, message="❌ Please specify which company the meeting was for. E.g., 'Meeting done for ABC Corp'", source=source)

    lead = get_lead_by_company(db, company_name)
    if not lead:
        return send_message(number=sender, message=f"❌ Lead not found for company: {company_name}", source=source)
 
    meeting_event = db.query(Event).filter(Event.lead_id == lead.id, Event.event_type.in_(["4 Phase Meeting", "Meeting"])).order_by(Event.event_time.desc()).first()
    if not meeting_event:
        return send_message(number=sender, message=f"⚠️ No meeting found for {company_name}", source=source)

    meeting_event.phase = "Done"
    db.commit()
    
    sender_user = get_user_by_phone(db, sender)
    sender_name = sender_user.username if sender_user else sender
    update_lead_status(db, lead_id=lead.id, status="Meeting Done", updated_by=sender_name, remark=remark if remark != "No remark provided." else "Meeting completed.")

    reply_parts = [
        f"✅ Meeting marked done for *{company_name}*.",
        "Do you need to update the core details for this lead (e.g., Company Name, Contact)?\n\nPlease reply with *Yes* or *No*."
    ]
    final_reply = "\n\n".join(reply_parts)

    pending_context[sender] = {"intent": "awaiting_details_change_decision", "company_name": company_name}
    logger.info(f"Set context for {sender} to 'awaiting_details_change_decision' for company '{company_name}'")

    return send_message(number=sender, message=final_reply, source=source)

async def handle_details_change_decision(db: Session, msg_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    context = pending_context.get(sender)
    if not context or context.get("intent") != "awaiting_details_change_decision":
        return send_message(number=sender, message="Sorry, I lost the context. How can I help?", source=source)

    company_name = context["company_name"]
    pending_context.pop(sender, None)

    positive_keywords = ["yes", "y", "ok", "okay", "sure", "do it"]
    if any(keyword in msg_text.lower().strip() for keyword in positive_keywords):
        ask_msg = "👍 Please provide the new details. For example:\n`Company Name: New XYZ Corp, Contact: Sunita, Phone: 9876543210`"
        pending_context[sender] = {"intent": "awaiting_core_lead_update", "company_name": company_name}
        logger.info(f"Set context for {sender} to 'awaiting_core_lead_update' for company '{company_name}'")
        return send_message(number=sender, message=ask_msg, source=source)
    else:
        logger.info(f"User chose not to update core details for {company_name}. Checking for other missing fields.")
        prompt_message, next_intent = _get_post_update_prompt(db, company_name)
        if next_intent:
            pending_context[sender] = {"intent": next_intent, "company_name": company_name}
        return send_message(number=sender, message=prompt_message, source=source)

async def handle_core_lead_update(db: Session, msg_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    context = pending_context.get(sender)
    if not context or context.get("intent") != "awaiting_core_lead_update":
        return send_message(number=sender, message="Sorry, I lost the context. How can I help?", source=source)

    original_company_name = context["company_name"]
    pending_context.pop(sender, None)

    lead = get_lead_by_company(db, original_company_name)
    if not lead:
        return send_message(number=sender, message=f"❌ Strange, I can no longer find the lead for {original_company_name}.", source=source)

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
    return send_message(number=sender, message=final_reply, source=source)

def _get_post_update_prompt(db: Session, company_name: str) -> (str, str or None):
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
        return send_message(number=sender, message="Sorry, I lost the context. How can I help?", source=source)

    company_name = context["company_name"]
    pending_context.pop(sender, None)

    reply_parts = []
    if "skip" in msg_text.lower():
        reply_parts.append("👍 Understood. Skipping additional details for now.")
    else:
        lead = get_lead_by_company(db, company_name)
        if not lead:
            return send_message(number=sender, message=f"❌ Strange, I can no longer find the lead for {company_name}.", source=source)
            
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
    
    return send_message(number=sender, message=final_reply, source=source)

def extract_company_name_from_meeting_update(msg_text: str) -> str:
    match = re.search(r"meeting done for (.+?)(?:\.|,| is| they|$)", msg_text, re.IGNORECASE)
    return match.group(1).strip() if match else ""

def extract_remark_from_meeting_update(msg_text: str) -> str:
    match = re.search(r"(they .*|remark[:\-]?\s*.+)", msg_text, re.IGNORECASE)
    return match.group(1).strip().lstrip("Remark:").strip() if match else "No remark provided."