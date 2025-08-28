# app/reminders.py
from datetime import datetime
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.models import Reminder, User
from app.message_sender import send_whatsapp_message
import asyncio
import logging

logger = logging.getLogger(__name__)

# This helper function to save a reminder is fine.
def schedule_reminder(
    db: Session,
    lead_id: int,
    user_id: int, 
    message: str,
    remind_at: datetime,
):
    reminder = Reminder(
        lead_id=lead_id,
        user_id=user_id,
        assigned_to=user_id, # Keep assigned_to for consistency if needed elsewhere
        message=message,
        remind_time=remind_at,
        status="pending",
        created_at=datetime.utcnow(),
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    return reminder

# This is the main background loop for sending reminders.
# It has been corrected to fetch user phone numbers correctly.
async def reminder_loop():
    """
    A continuous loop that runs in the background to check for and send due reminders.
    """
    while True:
        # Use a new session for each check to avoid stale session issues.
        db = SessionLocal()
        try:
            # --- CRITICAL FIX: Use utcnow() to compare against UTC timestamps ---
            now = datetime.utcnow()
            
            # The query now joins Reminder with User to get the phone number
            due_reminders_with_users = (
                db.query(Reminder, User.usernumber)
                .join(User, Reminder.user_id == User.id)
                .filter(Reminder.remind_time <= now, Reminder.status == "pending")
                .all()
            )

            if due_reminders_with_users:
                logger.info(f"Found {len(due_reminders_with_users)} due reminders to send.")

            for reminder, user_phone in due_reminders_with_users:
                try:
                    if not user_phone:
                        logger.warning(f"Skipping reminder ID {reminder.id} because user {reminder.user_id} has no phone number.")
                        reminder.status = "failed" # Mark as failed to avoid retrying
                        continue

                    # Send the WhatsApp message to the fetched user_phone
                    # Assuming you have a default reply_url for system-initiated messages
                    success = send_whatsapp_message(None, user_phone, f"⏰ Reminder: {reminder.message}")
                    
                    if success:
                        reminder.status = "sent"
                        logger.info(f"✅ Sent reminder ID {reminder.id} for lead_id={reminder.lead_id} to {user_phone}")
                    else:
                        reminder.status = "failed"
                        logger.error(f"❌ Failed to send reminder ID {reminder.id} via WhatsApp API.")

                except Exception as e:
                    reminder.status = "failed"
                    logger.error(f"❌ Exception sending reminder ID {reminder.id}: {e}", exc_info=True)
                finally:
                    db.commit() # Commit status change for each reminder individually

        except Exception as outer_e:
            logger.error(f"⚠️ An error occurred in the reminder loop: {outer_e}", exc_info=True)
            db.rollback()
        finally:
            db.close() # Always close the session

        # Sleep for 60 seconds (1 minute) between checks
        await asyncio.sleep(60)