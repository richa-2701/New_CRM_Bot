# app/reminders.py

from datetime import datetime
from sqlalchemy.orm import Session
from app.db import get_db, SessionLocal
from app.models import Reminder
from app.message_sender import send_whatsapp_message
import asyncio

# This method saves the reminder to DB (actual scheduling is manual via cron or external)
def schedule_reminder(
    db: Session,
    lead_id: int,
    assigned_to: str,
    message: str,
    remind_at: datetime,
):
    reminder = Reminder(
        lead_id=lead_id,
        assigned_to=assigned_to,
        message=message,
        remind_time=remind_at,
        status="pending",
        created_at=datetime.now(),
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    return reminder

# This method can be called periodically (e.g. every X minutes) or through a background task
def check_and_send_due_reminders():
    print("🔁 Checking reminders...")
    db = next(get_db())
    now = datetime.now()
    due_reminders = (
        db.query(Reminder)
        .filter(Reminder.remind_time <= now, Reminder.status == "pending")
        .all()
    )

    for reminder in due_reminders:
        try:
            send_whatsapp_message(None, reminder.assigned_to, f"⏰ Reminder: {reminder.message}")
            reminder.status = "sent"
            db.commit()
            print(f"✅ Sent reminder for lead_id={reminder.lead_id}")
        except Exception as e:
            print(f"❌ Failed to send reminder: {str(e)}")

# This is the loop to be used in main.py for continuous background checks
async def reminder_loop():
    while True:
        try:
            await asyncio.sleep(60*60*24)  # Check every 60 seconds
            print("🔁 Checking reminders...")
            db = next(get_db())
            now = datetime.now()
            due_reminders = (
                db.query(Reminder)
                .filter(Reminder.remind_time <= now, Reminder.status == "pending")
                .all()
            )
            for reminder in due_reminders:
                try:
                    send_whatsapp_message(None, reminder.assigned_to, f"⏰ Reminder: {reminder.message}")
                    reminder.status = "sent"
                    db.commit()
                    print(f"✅ Sent reminder for lead_id={reminder.lead_id}")
                except Exception as e:
                    db.rollback()
                    print(f"❌ Error sending WhatsApp message: {e}")
        except Exception as outer_e:
            print(f"⚠️ Outer error in reminder loop: {outer_e}")
