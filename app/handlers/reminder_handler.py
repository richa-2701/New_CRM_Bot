from sqlalchemy.orm import Session
from app.models import Reminder, Lead, User
from app.message_sender import send_whatsapp_message
from datetime import datetime, timedelta
import re


def handle_set_reminder(db: Session, message: str, sender: str, reply_url: str):
    try:
        # Extract lead name
        lead_match = re.search(r"for\s+(.*?)\s+(?:at|on)", message, re.IGNORECASE)
        lead_name = lead_match.group(1).strip() if lead_match else None

        # Extract reminder time
        time_match = re.search(r"(?:at|on)\s+(\d{1,2}:\d{2}(?:\s*[apAP][mM])?)", message)
        time_str = time_match.group(1) if time_match else None

        # Extract reminder message
        msg_match = re.search(r"remind me.*?to\s+(.*)", message, re.IGNORECASE)
        reminder_msg = msg_match.group(1).strip() if msg_match else "Follow up reminder"

        if not lead_name or not time_str:
            send_whatsapp_message(reply_url, sender, "⚠️ Please provide lead name and time like: 'Remind me to follow up with Acme Co at 5:00 PM'")
            return {"status": "error", "message": "Missing lead name or time"}

        # Parse time
        remind_time = parse_time(time_str)
        if not remind_time:
            send_whatsapp_message(reply_url, sender, "❌ Invalid time format. Use HH:MM AM/PM")
            return {"status": "error", "message": "Invalid time format"}

        # Fetch Lead and User
        lead = db.query(Lead).filter(Lead.company_name.ilike(f"%{lead_name}%")).first()
        user = db.query(User).filter(User.phone == sender).first()

        if not lead:
            send_whatsapp_message(reply_url, sender, f"⚠️ Could not find lead: {lead_name}")
            return {"status": "error", "message": "Lead not found"}
        if not user:
            send_whatsapp_message(reply_url, sender, f"⚠️ You are not recognized in the system.")
            return {"status": "error", "message": "User not found"}

        # Create reminder
        reminder = Reminder(
            lead_id=lead.id,
            user_id=user.id,
            remind_at=remind_time,
            message=reminder_msg,
            is_sent=False
        )
        db.add(reminder)
        db.commit()

        send_whatsapp_message(reply_url, sender, f"✅ Reminder set for {lead.company_name} at {remind_time.strftime('%I:%M %p')}.")
        return {"status": "success"}

    except Exception as e:
        db.rollback()
        send_whatsapp_message(reply_url, sender, f"❌ Error setting reminder: {str(e)}")
        return {"status": "error", "details": str(e)}


def parse_time(time_str: str) -> datetime:
    try:
        now = datetime.now()
        # Support HH:MM or HH:MM AM/PM
        if 'am' in time_str.lower() or 'pm' in time_str.lower():
            time_obj = datetime.strptime(time_str.strip().lower(), "%I:%M %p")
        else:
            time_obj = datetime.strptime(time_str.strip(), "%H:%M")
        return now.replace(hour=time_obj.hour, minute=time_obj.minute, second=0, microsecond=0)
    except Exception:
        return None
