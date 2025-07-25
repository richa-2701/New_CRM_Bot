#app/handlers/demo_handler.py
import re
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import dateparser
import logging

from app.models import Lead, Demo, Feedback, Reminder, User
from app.message_sender import send_message, send_whatsapp_message
from app.crud import get_user_by_phone, get_user_by_name, get_lead_by_company, update_lead_status, create_activity_log
from app.schemas import ActivityLogCreate

logger = logging.getLogger(__name__)

def extract_details_for_demo(text: str):
    """
    Parses messages like:
    - "Schedule demo for [Company] on [Date/Time]"
    - "Schedule demo for [Company] on [Date/Time] assigned to [User]"
    """
    company_name, assigned_to, demo_time_str = None, None, None
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
    match = re.search(
        r"(?:demo\s+done\s+for|reschedule\s+demo\s+for)\s+(.+?)(?:\s|$)",
        text,
        re.IGNORECASE
    )
    return match.group(1).strip() if match else ""

def extract_datetime(text: str) -> datetime:
    date_match = re.search(r"(?:on|at)\s+(.+)", text, re.IGNORECASE)
    if date_match:
        raw_date_string = date_match.group(1).strip()
        raw_date_string = re.split(r'\s+assigned\s+to', raw_date_string, flags=re.IGNORECASE)[0]
        parsed = dateparser.parse(raw_date_string, settings={"PREFER_DATES_FROM": "future", "DATE_ORDER": "DMY"})
        if parsed and parsed > datetime.now():
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
            return send_message(reply_url, sender, "⚠️ Invalid format. Use: `Schedule demo for [Company] on [Date]`", source)

        date_time = dateparser.parse(demo_time_str, settings={"PREFER_DATES_FROM": "future", "DATE_ORDER": "DMY"})
        if not date_time:
            return send_message(reply_url, sender, f"⚠️ Could not find a valid date/time in '{demo_time_str}'.", source)

        lead = get_lead_by_company(db, company_name)
        if not lead:
            return send_message(reply_url, sender, f"❌ Could not find lead with company: {company_name}", source)

        assignee_user = get_user_by_name(db, assigned_to_name) if assigned_to_name else get_user_by_name(db, lead.assigned_to)
        
        if not assignee_user:
            assignee_name_to_show = assigned_to_name or lead.assigned_to
            return send_message(reply_url, sender, f"❌ Could not find an assignee named '{assignee_name_to_show}'.", source)

        assignee_phone = assignee_user.usernumber
        assignee_name = assignee_user.username

        demo = Demo(
            lead_id=lead.id,
            assigned_to=assignee_phone,
            scheduled_by=sender,
            start_time=date_time,
            created_at=datetime.utcnow()
        )
        db.add(demo)
        db.commit()

        # --- REVISED NOTIFICATION AND RESPONSE LOGIC ---
        # 1. Independent assignee notification (always via WhatsApp)
        if assignee_phone and assignee_phone != sender:
            notification_msg = f"""📢 *You have been assigned a demo*

🏢 Company: {lead.company_name}
👤 Contact: {lead.contact_name} ({lead.phone})
🕒 Time: {date_time.strftime('%A, %b %d at %I:%M %p')}"""
            send_whatsapp_message(reply_url, assignee_phone, notification_msg)
            logger.info(f"Sent demo notification to {assignee_name} at {assignee_phone}")

        # 2. Confirmation message for the original sender
        confirmation_msg = f"✅ Demo scheduled for {company_name} on {date_time.strftime('%A, %b %d at %I:%M %p')}\n👤 Assigned to: {assignee_name}"
        
        # 3. Final unified response handles both app and WhatsApp
        return send_message(reply_url, sender, confirmation_msg, source)
    
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error scheduling demo: {e}", exc_info=True)
        return send_message(reply_url, sender, "❌ Failed to schedule demo due to an internal error.", source)

async def handle_demo_reschedule(db: Session, message_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    try:
        company_name = extract_company_name(message_text)
        if not company_name:
            return send_message(reply_url, sender, "⚠️ Company name not found. Use 'reschedule demo for [Company] on [Date]'", source)

        lead = get_lead_by_company(db, company_name)
        if not lead:
            return send_message(reply_url, sender, f"❌ No lead found for company '{company_name}'.", source)

        demo = db.query(Demo).filter(Demo.lead_id == lead.id).order_by(Demo.start_time.desc()).first()
        if not demo:
            return send_message(reply_url, sender, f"⚠️ No demo found for '{company_name}'.", source)

        new_datetime = extract_datetime(message_text)
        if not new_datetime:
            return send_message(reply_url, sender, "⚠️ Could not find a valid new date/time in the message.", source)

        old_time = demo.start_time.strftime('%d %b %Y at %I:%M %p')
        new_time_formatted = new_datetime.strftime('%A, %b %d at %I:%M %p')
        
        assignee_phone = demo.assigned_to
        assignee_name = "the assignee"

        assignee_user = extract_assignee(message_text, db)
        if assignee_user:
            demo.assigned_to = assignee_user.usernumber
            assignee_phone = assignee_user.usernumber
            assignee_name = assignee_user.username
        else:
            user_from_phone = db.query(User).filter(User.usernumber == assignee_phone).first()
            if user_from_phone:
                assignee_name = user_from_phone.username

        demo.start_time = new_datetime
        demo.updated_at = datetime.utcnow()
        db.commit()

        activity_details = f"Demo rescheduled from {old_time} to {new_time_formatted} by {sender}."
        create_activity_log(db, activity=ActivityLogCreate(lead_id=lead.id, phase=lead.status, details=activity_details))

        # --- REVISED NOTIFICATION AND RESPONSE ---
        if assignee_phone and assignee_phone != sender:
            notify_msg = f"""📢 *Demo Rescheduled*

🏢 Company: {lead.company_name}
📞 Contact: {lead.phone}
📅 New Time: {new_time_formatted}"""
            send_whatsapp_message(reply_url, assignee_phone, notify_msg)
            logger.info(f"Sent reschedule notification to {assignee_name} at {assignee_phone}")

        confirmation_msg = f"🔄 Demo for {company_name} was rescheduled to {new_time_formatted}."
        if assignee_user:
            confirmation_msg += f"\n👤 It is now assigned to: {assignee_name}"

        return send_message(reply_url, sender, confirmation_msg, source)

    except Exception as e:
        logger.error(f"❌ Error in demo reschedule: {e}", exc_info=True)
        db.rollback()
        return send_message(reply_url, sender, "❌ Failed to reschedule demo due to an internal error.", source)
    
async def handle_post_demo(db: Session, message_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    try:
        company_name = extract_company_name(message_text)
        if not company_name:
            return send_message(reply_url, sender, "⚠️ Please include the company name, e.g., 'demo done for [Company]'", source)

        logger.info(f"Handling post-demo for company: {company_name}")
        lead = get_lead_by_company(db, company_name)
        if not lead:
            return send_message(reply_url, sender, f"❌ Lead not found for company: {company_name}", source)

        demo = db.query(Demo).filter(Demo.lead_id == lead.id).order_by(Demo.start_time.desc()).first()
        if not demo:
             return send_message(reply_url, sender, f"⚠️ No demo record found for '{company_name}'.", source)

        demo_remark = message_text.strip()
        demo.phase = "Done"
        demo.remark = demo_remark
        demo.updated_at = datetime.utcnow()
        db.commit()

        update_lead_status(db, lead_id=lead.id, status="Demo Done", updated_by=sender, remark=demo_remark)

        follow_up_time = demo.start_time + timedelta(days=3)
        
        # Correctly find the user who was assigned the demo to set a reminder for them
        assignee_user = db.query(User).filter(User.usernumber == demo.assigned_to).first()
        if not assignee_user:
             logger.warning(f"Could not find user with number {demo.assigned_to} to set reminder. Skipping reminder.")
        else:
            reminder = Reminder(
                lead_id=lead.id,
                user_id=assignee_user.id,
                assigned_to=assignee_user.id,
                remind_time=follow_up_time,
                message=f"🔔 Follow-up with {company_name} after demo",
                status="follow up",
                created_at=datetime.utcnow()
            )
            db.add(reminder)
            db.commit()

        confirmation_msg = f"✅ Marked demo for '{company_name}' as Done and set a 3-day follow-up reminder for the assignee."
        return send_message(reply_url, sender, confirmation_msg, source)

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error in handle_post_demo: {e}", exc_info=True)
        return send_message(reply_url, sender, "❌ Failed to update demo status due to an internal error.", source)