#app/handlers/demo_handler.py
import re
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import dateparser
import logging

from app.models import Lead, Demo, Feedback, Reminder,User
from app.message_sender import send_message,send_whatsapp_message
# --- MODIFIED: Import `update_lead_status` for automatic activity logging ---
from app.crud import get_user_by_phone, get_user_by_name, get_lead_by_company, update_lead_status

logger = logging.getLogger(__name__)

def extract_company_name(text: str) -> str:
    match = re.search(
        r"(?:demo\s+done\s+for|demo\s+for|meeting\s+done\s+for|for)\s+(.+?)(?:\s+(?:on|at|by|is|they|and)\b|[.,]|$)",
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

def extract_assignee(text: str, db: Session):
    match = re.search(r"(?:assigned to|assign to)\s+([A-Za-z0-9]+)", text, re.IGNORECASE)
    if not match:
        return None

    assignee_raw = match.group(1).strip()
    user = get_user_by_phone(db, assignee_raw) if assignee_raw.isdigit() else get_user_by_name(db, assignee_raw)
    return user

async def handle_demo_schedule(db: Session, message_text: str, sender: str, reply_url: str,source: str = "whatsapp"):
    try:
        company_name = extract_company_name(message_text)
        if not company_name:
            response = send_message(reply_url, sender, "⚠️ Could not find the company name.", source)
            if source.lower() == "app":
                return response
            return {"status": "error", "message": "Company name missing"}

        date_time = extract_datetime(message_text)
        if not date_time:
            response = send_message(reply_url, sender, "⚠️ Could not find a valid date/time.", source)
            if source.lower() == "app":
                return response
            return {"status": "error", "message": "Datetime missing"}

        lead = db.query(Lead).filter(Lead.company_name.ilike(f"%{company_name}%")).first()
        if not lead:
            response = send_message(reply_url, sender, f"❌ Could not find lead with company: {company_name}", source)
            if source.lower() == "app":
                return response
            return {"status": "error", "message": "Lead not found"}

        assignee_user = extract_assignee(message_text, db)
        if not assignee_user:
            assignee_user = get_user_by_name(db, lead.assigned_to)

        assignee_phone = assignee_user.usernumber if assignee_user else lead.assigned_to
        assignee_name = assignee_user.username if assignee_user else lead.assigned_to

        demo = Demo(
            lead_id=lead.id,
            assigned_to=assignee_phone,
            scheduled_by=sender,
            start_time=date_time,
            created_at=datetime.utcnow()
        )
        db.add(demo)
        db.commit()

        response = send_message(reply_url, sender,
            f"✅ Demo scheduled for {company_name} on {date_time.strftime('%Y-%m-%d %I:%M %p')}\n👤 Assigned to: {assignee_name}", source)

        if assignee_phone and source.lower() != "app":
            send_message(reply_url, assignee_phone,
                f"""
📢 *You have been assigned a demo*

🏢 Company: {lead.company_name}
👤 Contact: {lead.contact_name} ({lead.phone})
🕒 Time: {date_time.strftime('%A, %b %d at %I:%M %p')}
""", source)

        if source.lower() == "app":
            return response
        return {"status": "success"}
    
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error scheduling demo: {e}", exc_info=True)
        response = send_message(reply_url, sender, f"❌ Failed to schedule demo: {str(e)}", source)
        if source.lower() == "app":
            return response
        return {"status": "error", "message": str(e)}


async def handle_demo_reschedule(db: Session, message_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    try:
        company_name = extract_company_name(message_text)
        if not company_name:
            response = send_message(reply_url, sender, "⚠️ Company name not found.", source)
            if source.lower() == "app":
                return response
            return {"status": "error", "message": "Company name missing"}

        lead = db.query(Lead).filter(Lead.company_name.ilike(f"%{company_name}%")).first()
        if not lead:
            response = send_message(reply_url, sender, f"❌ No lead found for company '{company_name}'.", source)
            if source.lower() == "app":
                return response
            return {"status": "error", "message": "Lead not found"}

        demo = db.query(Demo).filter(Demo.lead_id == lead.id).order_by(Demo.start_time.desc()).first()
        if not demo:
            response = send_message(reply_url, sender, f"⚠️ No demo found for '{company_name}'.", source)
            if source.lower() == "app":
                return response
            return {"status": "error", "message": "No demo found"}

        new_datetime = extract_datetime(message_text)
        if not new_datetime:
            response = send_message(reply_url, sender, "⚠️ Could not find a valid new date/time in the message.", source)
            if source.lower() == "app":
                return response
            return {"status": "error", "message": "Invalid or missing new datetime"}

        # Update assignee only if mentioned
        assignee_user = extract_assignee(message_text, db)
        if assignee_user:
            demo.assigned_to = assignee_user.usernumber

        demo.start_time = new_datetime
        demo.updated_at = datetime.utcnow()
        db.commit()

        response = send_message(reply_url, sender,
            f"🔄 Demo rescheduled for {company_name} on {new_datetime.strftime('%Y-%m-%d %I:%M %p')}.", source)
        
        if demo.assigned_to and source.lower() != "app":
            notify_msg = f"""
📢 *Demo Rescheduled*

🏢 Company: {lead.company_name}
📞 Contact: {lead.phone}
📅 New Time: {new_datetime.strftime('%A, %b %d at %I:%M %p')}
"""
            send_message(reply_url, demo.assigned_to, notify_msg, source)
        if source.lower() == "app":
            return response

        return {"status": "success", "message": "Demo rescheduled"}

    except Exception as e:
        logger.error(f"❌ Error in demo reschedule: {e}", exc_info=True)
        db.rollback()
        response = send_message(reply_url, sender, "❌ Failed to reschedule demo.", source)
        if source.lower() == "app":
            return response
        return {"status": "error", "message": str(e)}
    
async def handle_post_demo(db: Session, message_text: str, sender: str, reply_url: str, source: str = "whatsapp"):
    try:
        company_name = extract_company_name(message_text)
        logger.info(f"Handling post-demo for company: {company_name}")
        lead = get_lead_by_company(db, company_name)
        if not lead:
            response = send_message(reply_url, sender, f"❌ Lead not found for company: {company_name}", source)
            if source.lower() == "app":
                return response
            return {"status": "error", "message": "Company not found"}

        if not company_name:
            response = send_message(reply_url, sender, "⚠️ Please include the company name in your message.", source)
            if source.lower() == "app":
                return response
            return {"status": "error", "message": "Company name missing"}

        lead = db.query(Lead).filter(Lead.company_name.ilike(f"%{company_name}%")).first()
        if not lead:
            response = send_message(reply_url, sender, f"❌ Lead not found for '{company_name}'.")
            if source.lower() == "app":
                return response
            return {"status": "error", "message": "Lead not found"}

        demo = db.query(Demo).filter(Demo.lead_id == lead.id).order_by(Demo.start_time.desc()).first()
        if not demo:
             response = send_message(reply_url, sender, f"⚠️ No demo record found for '{company_name}'.", source)
             if source.lower() == "app":
                return response
             return {"status": "error", "message": "No demo found"}

        # ✅ Update demo status and save remark
        demo_remark = message_text.strip()
        demo.phase = "Done"
        demo.remark = demo_remark
        demo.updated_at = datetime.utcnow()
        db.commit() # Commit demo changes

        # --- MODIFIED: Use centralized function to update lead status and log activity ---
        update_lead_status(db, lead_id=lead.id, status="Demo Done", updated_by=sender, remark=demo_remark)

        # ⏰ Set reminder for follow-up after 3 days
        follow_up_time = demo.start_time + timedelta(days=3)

        # 🔄 Resolve username to user ID if needed
        user = db.query(User).filter((User.username == lead.assigned_to) | (User.id == lead.id)).first()
        if not user:
            raise Exception(f"Assigned user '{lead.assigned_to}' not found")

        reminder = Reminder(
            lead_id=lead.id,
            user_id=user.id,
            assigned_to=user.id,
            remind_time=follow_up_time,
            message=f"🔔 Follow-up with {company_name} after demo",
            status="follow up",
            created_at=datetime.utcnow()
        )
        db.add(reminder)
        db.commit() # Commit reminder

        response = send_message(reply_url, sender, f"✅ Marked demo for '{company_name}' as Done and set reminder.", source)
        if source.lower() == "app":
            return response
        return {"status": "success", "message": "Demo marked as done and reminder set"}

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error in handle_post_demo: {e}", exc_info=True)
        response = send_message(reply_url, sender, "❌ Failed to update demo status.", source)
        if source.lower() == "app":
            return response
        return {"status": "error", "message": str(e)}