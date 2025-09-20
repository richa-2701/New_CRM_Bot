# reminders.py
from datetime import datetime, date, time, timedelta
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.models import Reminder, User, LeadDripAssignment
from app.message_sender import send_whatsapp_message
from app.crud import get_active_drip_assignments, get_sent_step_ids_for_assignment, log_sent_drip_message
import asyncio
import logging

logger = logging.getLogger(__name__)

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
        assigned_to=user_id,
        message=message,
        remind_time=remind_at,
        status="pending",
        created_at=datetime.utcnow(),
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    return reminder

async def reminder_loop():
    """
    A continuous loop that runs in the background to check for and send due reminders.
    This version includes critical fixes for timezone handling and API calls.
    """
    while True:
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            
            due_reminders_with_users = (
                db.query(Reminder, User.usernumber)
                .join(User, Reminder.user_id == User.id)
                .filter(
                    Reminder.remind_time <= now, 
                    Reminder.status == "pending",
                    Reminder.is_hidden_from_activity_log == False
                )
                .all()
            )

            if due_reminders_with_users:
                logger.info(f"Found {len(due_reminders_with_users)} due reminders to send.")

            for reminder, user_phone in due_reminders_with_users:
                try:
                    if not user_phone:
                        logger.warning(f"Skipping reminder ID {reminder.id} because user {reminder.user_id} has no phone number.")
                        reminder.status = "failed"
                        continue

                    success = send_whatsapp_message(number=user_phone, message=f"⏰ Reminder: {reminder.message}")
                    
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
                    db.commit()

        except Exception as outer_e:
            logger.error(f"⚠️ An error occurred in the reminder loop: {outer_e}", exc_info=True)
            db.rollback()
        finally:
            db.close()

        await asyncio.sleep(60)



async def drip_campaign_loop():
    """A continuous background loop to process and send drip campaign messages."""
    while True:
        db = SessionLocal()
        try:
            today = date.today()
            now = datetime.utcnow().time()
            
            active_assignments = get_active_drip_assignments(db)
            
            for assignment in active_assignments:
                days_passed = (today - assignment.start_date).days
                
                if not assignment.lead or not assignment.lead.contacts:
                    logger.warning(f"Skipping drip assignment {assignment.id} for lead {assignment.lead_id} due to missing data.")
                    continue

                sent_step_ids = get_sent_step_ids_for_assignment(db, assignment.id)

                steps_to_process = [
                    step for step in assignment.drip_sequence.steps
                    if step.id not in sent_step_ids and step.day_to_send <= days_passed
                ]

                for step in steps_to_process:
                    try:
                        scheduled_time = time.fromisoformat(str(step.time_to_send))
                        
                        if step.day_to_send < days_passed or (step.day_to_send == days_passed and now >= scheduled_time):
                            message_content = step.message.message_content
                            
                            primary_contact = assignment.lead.contacts[0] if assignment.lead.contacts else None
                            if primary_contact and message_content:
                                success = send_whatsapp_message(
                                    number=primary_contact.phone,
                                    message=message_content
                                )
                                if success:
                                    log_sent_drip_message(db, assignment_id=assignment.id, step_id=step.id)
                                    logger.info(f"Sent drip message step {step.id} to lead {assignment.lead_id}.")
                                else:
                                    logger.error(f"Failed to send drip message step {step.id} to lead {assignment.lead_id}.")
                    except Exception as step_e:
                        logger.error(f"Error processing step {step.id} for assignment {assignment.id}: {step_e}", exc_info=True)

        except Exception as outer_e:
            logger.error(f"⚠️ An error occurred in the drip campaign loop: {outer_e}", exc_info=True)
            db.rollback()
        finally:
            db.close()

        await asyncio.sleep(300)