# app/handlers/message_router.py
import re
import logging
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.gpt_parser import parse_intent_and_fields, parse_lead_info
from app.message_sender import send_whatsapp_message
from app.crud import update_lead_status, get_user_by_name
from app.handlers import (
    lead_handler,
    qualification_handler,
    meeting_handler,
    demo_handler,
    reassignment_handler,
    reminder_handler,
)
from app.temp_store import temp_store
# Import the context dict directly to check its state
from app.handlers.qualification_handler import pending_context
from datetime import datetime

logger = logging.getLogger(__name__)

async def route_message(sender: str, message_text: str, reply_url: str):
    db: Session = SessionLocal()
    lowered_text = message_text.lower().strip()

    try:
        # 🔁 CRITICAL: First, check if there's a pending multi-step action for this user.
        if sender in pending_context:
            context = pending_context[sender]
            logger.info(f"Found pending context for {sender}: {context}")
            if context.get("intent") == "qualification_pending":
                logger.info(f"Routing follow-up message from {sender} to qualification handler.")
                return await qualification_handler.handle_qualification(
                    db=db,
                    msg_text=message_text,
                    sender=sender,
                    reply_url=reply_url,
                )
            elif context.get("intent") == "awaiting_qualification_details":
                logger.info(f"Routing qualification details update from {sender} to its handler.")
                return await qualification_handler.handle_qualification_update(
                    db=db,
                    msg_text=message_text,
                    sender=sender,
                    reply_url=reply_url,
                )
            # --- NEW ROUTING LOGIC ---
            elif context.get("intent") == "awaiting_meeting_details":
                logger.info(f"Routing meeting details update from {sender} to its handler.")
                return await meeting_handler.handle_meeting_details_update(
                    db=db,
                    msg_text=message_text,
                    sender=sender,
                    reply_url=reply_url,
                )
            # --- END NEW ROUTING LOGIC ---

        # If no pending action, parse the intent of the new message.
        intent, _ = parse_intent_and_fields(lowered_text)
        logger.info(f"Detected Intent: {intent} for message: '{message_text}'")

        greeting_keywords = [
            "hi", "hello", "hii", "hey", "new lead", "there is a new lead",
            "lead aya hai", "naya lead", "i got a lead", "lead mila hai", "ek lead hai"
        ]

        if any(lowered_text.strip() == kw for kw in greeting_keywords):
            polite_msg = (
                "👋 Hi! To create a new lead, please provide the following details:\n\n"
                "📌 Company Name\n"
                "👤 Concern Person Name\n"
                "📱 Phone Number\n"
                "📍 Source\n"
                "👨‍💼 Assigned To (Name or Phone)\n\n"
                "📒 Example:\n"
                "'There is a lead from ABC Pvt Ltd, contact is Ramesh (9876543210), Source Referral, interested in inventory software, assign to Banwari.'\n"
                "✅ Format 2: Comma-Separated \n ABC Pvt Ltd, Ramesh, 9876543210, Jaipur, Inventory Software, Banwari"
            )
            send_whatsapp_message(reply_url, sender, polite_msg)
            return {"status": "prompted_for_lead"}

        if intent == "new_lead":
            return await lead_handler.handle_new_lead(
                db=db,
                message_text=message_text,
                created_by=sender,
                reply_url=reply_url
            )

        if intent == "qualify_lead":
            return await qualification_handler.handle_qualification(
                db=db,
                msg_text=message_text,
                sender=sender,
                reply_url=reply_url,
            )

        elif "reschedule meeting" in lowered_text:
            return await meeting_handler.handle_reschedule_meeting(db, message_text, sender, reply_url)
        
        elif intent == "schedule_meeting":
            return await meeting_handler.handle_meeting_schedule(db, message_text, sender, reply_url)

        elif intent == "schedule_demo":
            return await demo_handler.handle_demo_schedule(db, message_text, sender, reply_url)

        elif "reschedule demo" in lowered_text or "demo reschedule" in lowered_text:
            return await demo_handler.handle_demo_reschedule(db, message_text, sender, reply_url)
            
        elif "meeting done" in lowered_text or "meeting is done" in lowered_text:
            return await meeting_handler.handle_post_meeting_update(db, message_text, sender, reply_url)

        elif intent == "demo_done":
            return await demo_handler.handle_post_demo(db, message_text, sender, reply_url)

        elif intent == "reminder":
            return await reminder_handler.handle_set_reminder(db, message_text, sender, reply_url)

        elif intent == "reassign_task":
            return await reassignment_handler.handle_reassignment(db, message_text, sender, reply_url)
            
        else:
            # Fallback message is now more accurate since conversational replies are handled
            # before this point.
            fallback = (
                "🤖 I didn't understand that command. You can say things like:\n"
                "➡️ 'New lead ...'\n"
                "➡️ 'Lead is qualified for ...'\n"
                "➡️ 'Schedule meeting with ...'"
            )
            send_whatsapp_message(reply_url, sender, fallback)
            return {"status": "unhandled"}

    except Exception as e:
        logger.error(f"❌ Exception in route_message: {e}", exc_info=True)
        # On a critical failure, clear the user's context to prevent them from being stuck.
        if sender in pending_context:
            pending_context.pop(sender, None)
        send_whatsapp_message(reply_url, sender, "❌ Internal error occurred.")
        return {"status": "error", "detail": str(e)}

    finally:
        db.close()