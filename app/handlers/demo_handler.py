# demo_handler
import re
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import dateparser
import logging

from app.models import Event, Lead, Demo, Feedback, Reminder, User
from app.message_sender import send_message, send_whatsapp_message
from app.crud import get_user_by_phone, get_user_by_name, get_lead_by_company, update_lead_status, create_activity_log, is_user_available, create_reminder
from app.schemas import ActivityLogCreate, ReminderCreate

logger = logging.getLogger(__name__)

# --- NEW: Define default durations ---
DEMO_DEFAULT_DURATION_MINUTES = 120

# --- CORRECTED REGULAR EXPRESSION ---
def extract_details_for_demo(text: str):
    """
    Parses messages like:
    - "Schedule demo for [Company] on [Date] at [Time]"
    - "Schedule demo for [Company] on [Date] at [Time] to [EndTime]"
    - "... assigned to [User]" (optional)
    """
    company_name, assigned_to, demo_time_str = None, None, None
    # This regex now uses a non-capturing group for "to [end time]" to make it optional
    # and ensures it captures the full time string correctly.
    match = re.search(
        r"schedule\s+demo\s+for\s+(.+?)\s+(?:on|at)\s+(.+?)(?:\s+assigned\s+to\s+(.+))?$",
        text, re.IGNORECASE
    )
    if match:
        company_name = match.group(1).strip()
        demo_time_str = match.group(2).strip()
        assigned_to = match.group(3).strip() if match.group(3) else None
    return company_name, assigned_to, demo_time_str

def extract_company_name(text: str) -> str:
    
    # The pattern `(.+?)` is non-greedy. It will capture everything after the trigger phrase
    # up until the next part of the pattern, which is a word boundary `\b` or the end of the string `$`.
    # This prevents it from capturing the entire sentence.
    match = re.search(
        r"(?:demo\s+done\s+for|reschedule\s+demo\s+for)\s+(.+?)(?:\.|,|\bthey\b|\bon\b|\bat\b|$)",
        text,
        re.IGNORECASE
    )
    return match.group(1).strip() if match else ""

def extract_datetime(text: str) -> datetime:
    date_match = re.search(r"(?:on|at)\s+(.+)", text, re.IGNORECASE)
    if date_match:
        raw_date_string = date_match.group(1).strip()
        raw_date_string = re.split(r'\s+assigned\s+to', raw_date_string, flags=re.IGNORECASE)[0]
        # --- FIX APPLIED: Removed 'PREFER_DATES_FROM': 'future' for accurate parsing ---
        parsed = dateparser.parse(raw_date_string, settings={"DATE_ORDER": "DMY"})
        if parsed and parsed > datetime.utcnow(): # Explicitly check for future date
            return parsed
    return None

def extract_assignee(text: str, db: Session):
    match = re.search(r"(?:assigned to|assign to)\s+([A-Za-z0-9\s]+)", text, re.IGNORECASE)
    if not match:
        return None
    assignee_raw = match.group(1).strip()
    user = get_user_by_phone(db, assignee_raw) if assignee_raw.isdigit() else get_user_by_name(db, assignee_raw)
    return user

async def handle_demo_schedule(db: Session, message_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    try:
        company_name, assigned_to_name, demo_time_str = extract_details_for_demo(message_text)

        if not company_name or not demo_time_str:
            return send_message(number=sender, message="⚠️ Invalid format. Use: `Schedule demo for [Company] on [Date]`", source=source)

        start_time = None
        end_time = None

        time_range_match = re.search(r'at\s(.+?)\s+to\s+(.+)', demo_time_str, re.IGNORECASE)
        if time_range_match:
            start_str = time_range_match.group(1).strip()
            end_str = time_range_match.group(2).strip()
            start_time = dateparser.parse(start_str, settings={'DATE_ORDER': 'DMY'})
            end_time = dateparser.parse(end_str, settings={'DATE_ORDER': 'DMY'})
            
            if start_time and end_time and end_time.date() == start_time.date():
                 end_time = end_time.replace(year=start_time.year, month=start_time.month, day=start_time.day)
        
        if not start_time or not end_time:
            start_time = dateparser.parse(demo_time_str, settings={'DATE_ORDER': 'DMY'})
            if start_time:
                end_time = start_time + timedelta(minutes=DEMO_DEFAULT_DURATION_MINUTES)
        
        if not start_time:
            return send_message(number=sender, message=f"⚠️ Could not find a valid date/time in '{demo_time_str}'.", source=source)
        
        if start_time < datetime.utcnow():
            error_msg = f"❌ The start time you entered ({start_time.strftime('%d-%b-%Y %I:%M %p')}) is in the past. Please use a future date."
            return send_message(number=sender, message=error_msg, source=source)

        lead = get_lead_by_company(db, company_name)
        if not lead:
            return send_message(number=sender, message=f"❌ Could not find lead with company: {company_name}", source=source)

        assignee_user = get_user_by_name(db, assigned_to_name) if assigned_to_name else get_user_by_name(db, lead.assigned_to)
        if not assignee_user:
            assignee_name_to_show = assigned_to_name or lead.assigned_to
            return send_message(number=sender, message=f"❌ Could not find an assignee named '{assignee_name_to_show}'.", source=source)

        assignee_phone = assignee_user.usernumber
        assignee_name = assignee_user.username

        conflict = is_user_available(db, assignee_name, assignee_phone, start_time, end_time)
        if conflict:
            conflict_type = "Meeting" if isinstance(conflict, Event) else "Demo"
            conflict_lead = db.query(Lead).filter(Lead.id == conflict.lead_id).first()
            conflict_lead_name = conflict_lead.company_name if conflict_lead else "another task"
            conflict_start_time = conflict.event_time if isinstance(conflict, Event) else conflict.start_time
            error_msg = (
                f"❌ Scheduling failed. *{assignee_name}* is already booked at that time.\n\n"
                f"Conflict: {conflict_type} with *{conflict_lead_name}*\n"
                f"Time: {conflict_start_time.strftime('%I:%M %p')}"
            )
            return send_message(number=sender, message=error_msg, source=source)

        demo = Demo(
            lead_id=lead.id,
            assigned_to=assignee_phone,
            scheduled_by=sender,
            start_time=start_time,
            event_end_time=end_time,
            created_at=datetime.utcnow()
        )
        db.add(demo)
        db.commit()
        db.refresh(demo)

        time_formatted = start_time.strftime('%A, %b %d at %I:%M %p')
        reminder_message = f"You have a demo scheduled for *{lead.company_name}* on {time_formatted}."

        one_day_before = start_time - timedelta(days=1)
        if one_day_before > datetime.utcnow():
            create_reminder(db, ReminderCreate(
                lead_id=lead.id, user_id=assignee_user.id, assigned_to=assignee_user.username,
                remind_time=one_day_before, message=f" (1 day away) {reminder_message}",
                is_hidden_from_activity_log=True
            ))

        one_hour_before = start_time - timedelta(hours=1)
        if one_hour_before > datetime.utcnow():
            create_reminder(db, ReminderCreate(
                lead_id=lead.id, user_id=assignee_user.id, assigned_to=assignee_user.username,
                remind_time=one_hour_before, message=f" (in 1 hour) {reminder_message}",
                is_hidden_from_activity_log=True
            ))
        
        logger.info(f"Scheduled pre-demo reminders for demo ID {demo.id}")

        if assignee_phone and assignee_phone != sender:
            # --- CRITICAL FIX START ---
            # Safely get contact name and phone from the lead's contacts list
            contact_name_for_msg = lead.contacts[0].contact_name if lead.contacts and lead.contacts[0].contact_name else 'N/A'
            contact_phone_for_msg = lead.contacts[0].phone if lead.contacts and lead.contacts[0].phone else 'N/A'

            notification_msg = f"""📢 *You have been assigned a demo*

🏢 Company: {lead.company_name}
👤 Contact: {contact_name_for_msg} ({contact_phone_for_msg})
🕒 Time: {start_time.strftime('%A, %b %d at %I:%M %p')}"""
            # --- CRITICAL FIX END ---
            send_whatsapp_message(number=assignee_phone, message=notification_msg)
            logger.info(f"Sent demo notification to {assignee_name} at {assignee_phone}")

        confirmation_msg = f"✅ Demo scheduled for {company_name} on {start_time.strftime('%A, %b %d at %I:%M %p')}\n👤 Assigned to: {assignee_name}. Reminders have been set."
        
        return send_message(number=sender, message=confirmation_msg, source=source)
    
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error scheduling demo: {e}", exc_info=True)
        return send_message(number=sender, message="❌ Failed to schedule demo due to an internal error.", source=source)

async def handle_demo_reschedule(db: Session, message_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    try:
        reschedule_match = re.search(r"reschedule\s+demo\s+for\s+(.+?)\s+(?:on|at)\s+(.+)", message_text, re.IGNORECASE)
        if not reschedule_match:
             return send_message(number=sender, message="⚠️ Invalid format. Use: `reschedule demo for [Company] on [Date]`", source=source)
        
        company_name = reschedule_match.group(1).strip()
        new_time_str = reschedule_match.group(2).strip()

        lead = get_lead_by_company(db, company_name)
        if not lead:
            return send_message(number=sender, message=f"❌ No lead found for company '{company_name}'.", source=source)

        demo = db.query(Demo).filter(Demo.lead_id == lead.id).order_by(Demo.start_time.desc()).first()
        if not demo:
            return send_message(number=sender, message=f"⚠️ No demo found for '{company_name}'.", source=source)

        new_start_time = None
        new_end_time = None

        time_range_match = re.search(r'at\s(.+?)\s+to\s+(.+)', new_time_str, re.IGNORECASE)
        if time_range_match:
            start_str = time_range_match.group(1).strip()
            end_str = time_range_match.group(2).strip()
            new_start_time = dateparser.parse(start_str, settings={'DATE_ORDER': 'DMY'})
            new_end_time = dateparser.parse(end_str, settings={'DATE_ORDER': 'DMY'})
            if new_start_time and new_end_time and new_end_time.date() == new_start_time.date():
                new_end_time = new_end_time.replace(year=new_start_time.year, month=new_start_time.month, day=new_start_time.day)
        
        if not new_start_time or not new_end_time:
            new_start_time = dateparser.parse(new_time_str, settings={'DATE_ORDER': 'DMY'})
            if new_start_time:
                new_end_time = new_start_time + timedelta(minutes=DEMO_DEFAULT_DURATION_MINUTES)
        
        if not new_start_time:
            return send_message(number=sender, message=f"⚠️ Could not find a valid new date/time in '{new_time_str}'.", source=source)
        
        if new_start_time < datetime.utcnow():
            error_msg = f"❌ The new start time you entered ({new_start_time.strftime('%d-%b-%Y %I:%M %p')}) is in the past. Please use a future date."
            return send_message(number=sender, message=error_msg, source=source)

        old_time = demo.start_time.strftime('%d %b %Y at %I:%M %p')
        new_time_formatted = new_start_time.strftime('%A, %b %d at %I:%M %p')
        
        final_assignee_user = extract_assignee(message_text, db)
        if not final_assignee_user:
            final_assignee_user = db.query(User).filter(User.usernumber == demo.assigned_to).first()

        if not final_assignee_user:
             logger.error(f"Could not find user for phone number {demo.assigned_to} during reschedule.")
             return send_message(number=sender, message="❌ Internal error: Could not verify assignee.", source=source)

        assignee_name = final_assignee_user.username
        assignee_phone = final_assignee_user.usernumber
        
        conflict = is_user_available(db, assignee_name, assignee_phone, new_start_time, new_end_time, exclude_demo_id=demo.id)
        if conflict:
            conflict_type = "Meeting" if isinstance(conflict, Event) else "Demo"
            conflict_lead = db.query(Lead).filter(Lead.id == conflict.lead_id).first()
            conflict_lead_name = conflict_lead.company_name if conflict_lead else "another task"
            conflict_start_time = conflict.event_time if isinstance(conflict, Event) else conflict.start_time
            error_msg = f"❌ Rescheduling failed. *{assignee_name}* is already booked at that time.\n\nConflict: {conflict_type} with *{conflict_lead_name}* at {conflict_start_time.strftime('%I:%M %p')}"
            return send_message(number=sender, message=error_msg, source=source)

        db.query(Reminder).filter(
            Reminder.lead_id == lead.id, 
            Reminder.message.like(f"%demo scheduled for *{lead.company_name}*%")
        ).delete(synchronize_session=False)
        
        time_formatted = new_start_time.strftime('%A, %b %d at %I:%M %p')
        reminder_message = f"You have a demo scheduled for *{lead.company_name}* on {time_formatted}."

        one_day_before = new_start_time - timedelta(days=1)
        if one_day_before > datetime.utcnow():
            create_reminder(db, ReminderCreate(
                lead_id=lead.id, user_id=final_assignee_user.id, assigned_to=final_assignee_user.username,
                remind_time=one_day_before, message=f" (1 day away) {reminder_message}",
                is_hidden_from_activity_log=True
            ))

        one_hour_before = new_start_time - timedelta(hours=1)
        if one_hour_before > datetime.utcnow():
            create_reminder(db, ReminderCreate(
                lead_id=lead.id, user_id=final_assignee_user.id, assigned_to=final_assignee_user.username,
                remind_time=one_hour_before, message=f" (in 1 hour) {reminder_message}",
                is_hidden_from_activity_log=True
            ))
        
        logger.info(f"Re-scheduled pre-demo reminders for demo ID {demo.id}")

        demo.start_time = new_start_time
        demo.event_end_time = new_end_time
        demo.assigned_to = assignee_phone
        demo.updated_at = datetime.utcnow()
        db.commit()

        activity_details = f"Demo rescheduled from {old_time} to {new_time_formatted} by {sender}."
        create_activity_log(db, activity=ActivityLogCreate(lead_id=lead.id, phase=lead.status, details=activity_details))

        if assignee_phone and assignee_phone != sender:
            notify_msg = f"""📢 *Demo Rescheduled*

🏢 Company: {lead.company_name}
📞 Contact: {lead.phone}
📅 New Time: {new_time_formatted}"""
            send_whatsapp_message(number=assignee_phone, message=notify_msg)
            logger.info(f"Sent reschedule notification to {assignee_name} at {assignee_phone}")

        confirmation_msg = f"🔄 Demo for {company_name} was rescheduled to {new_time_formatted}. Reminders have been updated."
        if extract_assignee(message_text, db):
            confirmation_msg += f"\n👤 It is now assigned to: {assignee_name}"

        return send_message(number=sender, message=confirmation_msg, source=source)

    except Exception as e:
        logger.error(f"❌ Error in demo reschedule: {e}", exc_info=True)
        db.rollback()
        return send_message(number=sender, message="❌ Failed to reschedule demo due to an internal error.", source=source)



async def handle_post_demo(db: Session, message_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    try:
        company_name = extract_company_name(message_text)
        if not company_name:
            return send_message(number=sender, message="⚠️ Please include the company name, e.g., 'demo done for [Company]'", source=source)

        logger.info(f"Handling post-demo for company: {company_name}")
        lead = get_lead_by_company(db, company_name)
        if not lead:
            return send_message(number=sender, message=f"❌ Lead not found for company: {company_name}", source=source)

        demo = db.query(Demo).filter(Demo.lead_id == lead.id).order_by(Demo.start_time.desc()).first()
        if not demo:
             return send_message(number=sender, message=f"⚠️ No demo record found for '{company_name}'.", source=source)

        demo_remark = message_text.strip()
        demo.phase = "Done"
        demo.remark = demo_remark
        demo.updated_at = datetime.utcnow()
        db.commit()

        update_lead_status(db, lead_id=lead.id, status="Demo Done", updated_by=sender, remark=demo_remark)

        follow_up_time = demo.start_time + timedelta(days=3)
        
        assignee_user = db.query(User).filter(User.usernumber == demo.assigned_to).first()
        if not assignee_user:
             logger.warning(f"Could not find user with number {demo.assigned_to} to set reminder. Skipping reminder.")
        else:
            reminder = Reminder(
                lead_id=lead.id,
                user_id=assignee_user.id,
                assigned_to=assignee_user.username,
                remind_time=follow_up_time,
                message=f"🔔 Follow-up with {company_name} after demo",
                status="follow up",
                created_at=datetime.utcnow()
            )
            db.add(reminder)
            db.commit()

        confirmation_msg = f"✅ Marked demo for '{company_name}' as Done and set a 3-day follow-up reminder for the assignee."
        return send_message(number=sender, message=confirmation_msg, source=source)

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error in handle_post_demo: {e}", exc_info=True)
        return send_message(number=sender, message="❌ Failed to update demo status due to an internal error.", source=source)