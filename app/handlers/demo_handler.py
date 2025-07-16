# ✅ UPDATED demo_handler.py

import re
from datetime import datetime
from sqlalchemy.orm import Session
import dateparser
import logging

from app.models import Lead, Demo
from app.message_sender import send_whatsapp_message
from app.crud import get_user_by_phone, get_user_by_name

logger = logging.getLogger(__name__)

def extract_company_name(text: str) -> str:
    match = re.search(
        r"(?:demo\s+for|meeting\s+done\s+for|for)\s+(.*?)(?=\s+(on|at|by|is|they|and|\.|,|$))",
        text,
        re.IGNORECASE
    )
    return match.group(1).strip() if match else ""

def extract_datetime(text: str) -> datetime:
    date_match = re.search(
        r"(?:on|at)\s+([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4}(?:\s+[0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?)?)",
        text, re.IGNORECASE
    )
    if date_match:
        raw_date = date_match.group(1).strip()
        parsed = dateparser.parse(raw_date, settings={"PREFER_DATES_FROM": "future"})
        if parsed and parsed > datetime.now():
            return parsed
    return None

async def handle_demo_schedule(db: Session, message_text: str, sender: str, reply_url: str):
    try:
        company_name = extract_company_name(message_text)
        if not company_name:
            send_whatsapp_message(reply_url, sender, "⚠️ Could not find the company name.")
            return {"status": "error", "message": "Company name missing"}

        date_time = extract_datetime(message_text)
        if not date_time:
            send_whatsapp_message(reply_url, sender, "⚠️ Could not find a valid date/time.")
            return {"status": "error", "message": "Datetime missing"}

        lead = db.query(Lead).filter(Lead.company_name.ilike(f"%{company_name}%")).first()
        if not lead:
            send_whatsapp_message(reply_url, sender, f"❌ Could not find lead with company: {company_name}")
            return {"status": "error", "message": "Lead not found"}

        phone_match = re.search(r"assigned to\s+(\d{10})", message_text)
        assignee_phone = phone_match.group(1) if phone_match else lead.assigned_to

        assignee_name = ""
        if assignee_phone:
            user = get_user_by_phone(db, assignee_phone)
            assignee_name = user.name if user else assignee_phone
        else:
            fallback_user = get_user_by_name(db, "Banwari")
            assignee_phone = fallback_user.phone if fallback_user else ""
            assignee_name = fallback_user.name if fallback_user else ""

        demo = Demo(
            lead_id=lead.id,
            assigned_to=assignee_phone,
            scheduled_by=sender,
            start_time=date_time,
            created_at=datetime.utcnow()
        )
        db.add(demo)
        db.commit()

        send_whatsapp_message(reply_url, sender,
            f"✅ Demo scheduled for {company_name} on {date_time.strftime('%Y-%m-%d %I:%M %p')}\n👤 Assigned to: {assignee_name}")

        if assignee_phone:
            send_whatsapp_message(reply_url, assignee_phone,
                f"""
📢 *You have been assigned a demo*

🏢 Company: {lead.company_name}
👤 Contact: {lead.contact_name} ({lead.phone})
🕒 Time: {date_time.strftime('%A, %b %d at %I:%M %p')}
""")

        return {"status": "success"}

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error scheduling demo: {e}", exc_info=True)
        send_whatsapp_message(reply_url, sender, f"❌ Failed to schedule demo: {str(e)}")
        return {"status": "error", "message": str(e)}


async def handle_demo_reschedule(db: Session, message_text: str, sender: str, reply_url: str):
    try:
        company_name = extract_company_name(message_text)
        if not company_name:
            send_whatsapp_message(reply_url, sender, "⚠️ Company name not found.")
            return {"status": "error", "message": "Company name missing"}

        lead = db.query(Lead).filter(Lead.company_name.ilike(f"%{company_name}%")).first()
        if not lead:
            send_whatsapp_message(reply_url, sender, f"❌ No lead found for company '{company_name}'.")
            return {"status": "error", "message": "Lead not found"}

        demo = db.query(Demo).filter(Demo.lead_id == lead.id).order_by(Demo.start_time.desc()).first()
        if not demo:
            send_whatsapp_message(reply_url, sender, f"⚠️ No demo found for '{company_name}'.")
            return {"status": "error", "message": "No demo found"}

        new_datetime = extract_datetime(message_text)
        if not new_datetime:
            send_whatsapp_message(reply_url, sender, "⚠️ Could not find a valid new date/time in the message.")
            return {"status": "error", "message": "Invalid or missing new datetime"}

        demo.start_time = new_datetime
        demo.updated_at = datetime.utcnow()
        db.commit()

        send_whatsapp_message(
            reply_url,
            sender,
            f"🔄 Demo rescheduled for {company_name} on {new_datetime.strftime('%Y-%m-%d %I:%M %p')}."
        )

        if demo.assigned_to:
            notify_msg = f"""
            📢 *Demo Rescheduled*

            🏢 Company: {lead.company_name}
            📞 Contact: {lead.phone}
            📅 New Time: {new_datetime.strftime('%A, %b %d at %I:%M %p')}
            """
            send_whatsapp_message(reply_url, demo.assigned_to, notify_msg)

        return {"status": "success", "message": "Demo rescheduled"}

    except Exception as e:
        logger.error(f"❌ Error in demo reschedule: {e}", exc_info=True)
        db.rollback()
        send_whatsapp_message(reply_url, sender, "❌ Failed to reschedule demo.")
        return {"status": "error", "message": str(e)}


async def handle_post_demo_feedback(db: Session, message_text: str, sender: str, reply_url: str):
    try:
        company_name = extract_company_name(message_text)
        if not company_name:
            send_whatsapp_message(reply_url, sender, "⚠️ Please mention the company name for which demo is done.")
            return {"status": "error", "message": "Company name missing"}

        lead = db.query(Lead).filter(Lead.company_name.ilike(f"%{company_name}%")).first()
        if not lead:
            send_whatsapp_message(reply_url, sender, f"❌ Lead not found for '{company_name}'.")
            return {"status": "error", "message": "Lead not found"}

        # Store feedback
        feedback = Feedback(
            lead_id=lead.id,
            feedback_by=sender,
            content=message_text,
            created_at=datetime.utcnow()
        )
        db.add(feedback)

        # Create follow-up reminder for 3 days later
        demo = db.query(Demo).filter(Demo.lead_id == lead.id).order_by(Demo.start_time.desc()).first()
        if demo:
            remind_time = demo.start_time + timedelta(days=3)
            reminder = Reminder(
                lead_id=lead.id,
                user_id=lead.assigned_to,
                assigned_to=lead.assigned_to,
                remind_time=remind_time,
                message=f"🔔 Follow-up with {lead.company_name} after demo",
            )
            db.add(reminder)

        db.commit()

        send_whatsapp_message(reply_url, sender, f"✅ Feedback saved for demo with {lead.company_name}.")
        return {"status": "success"}

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error in post-demo feedback: {e}", exc_info=True)
        send_whatsapp_message(reply_url, sender, "❌ Failed to record feedback.")
        return {"status": "error", "message": str(e)}
