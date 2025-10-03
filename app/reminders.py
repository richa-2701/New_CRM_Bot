# app/reminders.py
from datetime import datetime, date, time, timedelta
from sqlalchemy.orm import Session
from app.db import get_db_session_for_company, COMPANY_TO_ENV_MAP
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
    """
    This function does NOT need to change. It is called from endpoints that
    already have a database session for a specific company.
    """
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
    A continuous loop that runs in the background to check for and send due reminders
    across ALL configured company databases.
    """
    while True:
        logger.info("⏰ Starting reminder check cycle for all companies...")
        
        all_companies = list(COMPANY_TO_ENV_MAP.keys())
        
        for company in all_companies:
            logger.info(f"-> Checking reminders for company: '{company}'")
            
            db: Session = get_db_session_for_company(company)
            
            try:
                now = datetime.utcnow()
                
                # --- START OF FIX: Corrected the query ---
                due_reminders_with_users = (
                    db.query(Reminder, User)
                    .join(User, Reminder.user_id == User.id)
                    .filter(
                        Reminder.remind_time <= now, 
                        Reminder.status == "pending"
                    )
                    .all()
                )
                # --- END OF FIX ---

                if due_reminders_with_users:
                    logger.info(f"   Found {len(due_reminders_with_users)} due reminders for '{company}'.")

                for reminder, user in due_reminders_with_users:
                    try:
                        if not user.usernumber:
                            logger.warning(f"   Skipping reminder ID {reminder.id} for '{company}' because user {user.username} has no phone number.")
                            reminder.status = "failed"
                            continue

                        success = send_whatsapp_message(number=user.usernumber, message=f"⏰ Reminder: {reminder.message}")
                        
                        if success:
                            reminder.status = "sent"
                            logger.info(f"   ✅ Sent reminder ID {reminder.id} for '{company}' to {user.usernumber}")
                        else:
                            reminder.status = "failed"
                            logger.error(f"   ❌ Failed to send reminder ID {reminder.id} for '{company}' via WhatsApp API.")

                    except Exception as e:
                        reminder.status = "failed"
                        logger.error(f"   ❌ Exception sending reminder ID {reminder.id} for '{company}': {e}", exc_info=True)
                    finally:
                        db.commit()

            except Exception as outer_e:
                logger.error(f"⚠️ An error occurred in the reminder loop for company '{company}': {outer_e}", exc_info=True)
                db.rollback()
            finally:
                db.close()
                logger.info(f"   Session closed for '{company}'.")

        logger.info("Finished reminder cycle. Waiting for 60 seconds.")
        await asyncio.sleep(60)



async def drip_campaign_loop():
    """
    A continuous background loop to process and send drip campaign messages
    across ALL configured company databases.
    """
    while True:
        logger.info("💧 Starting drip campaign check cycle for all companies...")

        all_companies = list(COMPANY_TO_ENV_MAP.keys())

        for company in all_companies:
            logger.info(f"-> Checking drip campaigns for company: '{company}'")
            db: Session = get_db_session_for_company(company)

            try:
                today = date.today()
                now = datetime.utcnow().time()
                
                active_assignments = get_active_drip_assignments(db)
                
                if not active_assignments:
                    logger.info(f"   No active drip campaigns found for '{company}'.")

                for assignment in active_assignments:
                    days_passed = (today - assignment.start_date).days
                    
                    if not assignment.lead or not assignment.lead.contacts:
                        logger.warning(f"   Skipping drip assignment {assignment.id} for lead {assignment.lead_id} in '{company}' due to missing data.")
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
                                        logger.info(f"   Sent drip message step {step.id} to lead {assignment.lead_id} in '{company}'.")
                                    else:
                                        logger.error(f"   Failed to send drip message step {step.id} to lead {assignment.lead_id} in '{company}'.")
                        except Exception as step_e:
                            logger.error(f"   Error processing step {step.id} for assignment {assignment.id} in '{company}': {step_e}", exc_info=True)

            except Exception as outer_e:
                logger.error(f"⚠️ An error occurred in the drip campaign loop for '{company}': {outer_e}", exc_info=True)
                db.rollback()
            finally:
                db.close()
                logger.info(f"   Session closed for '{company}'.")
        
        logger.info("Finished drip campaign cycle. Waiting for 5 minutes.")
        await asyncio.sleep(300)