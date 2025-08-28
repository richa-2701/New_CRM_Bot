# app/handlers/message_router.py
import re
import logging
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.gpt_parser import parse_intent_and_fields, parse_lead_info, parse_update_company
from app.message_sender import send_whatsapp_message,send_message
from app.crud import update_lead_status, get_user_by_name, get_lead_by_company
from app.handlers import (
    lead_handler,
    qualification_handler,
    meeting_handler,
    demo_handler,
    reassignment_handler,
    reminder_handler,
    activity_handler,
    # --- THIS IS THE CORRECTED LINE ---
    # Add the new discussion_handler to the list of imports
    discussion_handler,
    # --- END CORRECTION ---
)
from app.temp_store import temp_store
from app.handlers.qualification_handler import pending_context
from datetime import datetime

logger = logging.getLogger(__name__)

def extract_company_name(text: str) -> str:
    patterns = [
        r"(?:for|with|of)\s+([A-Za-z0-9\s&.'-]+?)(?=\s+on|\s+at|\s+to|\s+next|\s+is|$|,)"
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            company = match.group(1).strip()
            if company.lower() in ["the", "a", "an"]:
                continue
            return company
    return ""

async def route_message(sender: str, message_text: str, reply_url: str,source: str = "whatsapp")-> dict:
    db: Session = SessionLocal()
    lowered_text = message_text.lower().strip()

    try:
        if sender in pending_context:
            context = pending_context[sender]
            logger.info(f"Found pending context for {sender}: {context}")
            
            context_handlers = {
                "qualification_pending": qualification_handler.handle_qualification,
                "awaiting_qualification_details": qualification_handler.handle_qualification_update,
                "awaiting_4_phase_decision": qualification_handler.handle_4_phase_decision,
                "awaiting_details_change_decision": meeting_handler.handle_details_change_decision,
                "awaiting_core_lead_update": meeting_handler.handle_core_lead_update,
                "awaiting_meeting_details": meeting_handler.handle_meeting_details_update,
            }

            handler = context_handlers.get(context.get("intent"))
            if handler:
                logger.info(f"Routing message from {sender} to {context.get('intent')} handler.")
                return await handler(db=db, msg_text=message_text, sender=sender, reply_url=reply_url, source=source)

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
                "'There is a lead from ABC Pvt Ltd, contact is Ramesh (9876543210), Source Referral, assign to Banwari.'"
            )
            return send_message(reply_url, sender, polite_msg, source)
        
        # --- THIS IS THE CORRECTED CODE BLOCK ---
        # Added the new routing logic for discussion management.
        # The router will now check for these specific keywords.

        if "discussion done for" in lowered_text:
            return await discussion_handler.handle_discussion_done(db, message_text, sender, reply_url, source)
        
        elif "schedule discussion for" in lowered_text:
            return await discussion_handler.handle_schedule_discussion(db, message_text, sender, reply_url, source)

        elif "log discussion for" in lowered_text:
            return await discussion_handler.handle_log_discussion(db, message_text, sender, reply_url, source)
            
        # --- END CORRECTION ---

        elif "add activity for" in lowered_text:
            return await activity_handler.handle_add_activity(db, message_text, sender, reply_url, source)
        
        elif intent == "new_lead":
            return await lead_handler.handle_new_lead(db=db, message_text=message_text, created_by=sender, reply_url=reply_url, source=source)

        elif intent == "qualify_lead":
            return await qualification_handler.handle_qualification(db=db, msg_text=message_text, sender=sender, reply_url=reply_url, source=source)

        elif "reschedule meeting" in lowered_text:
            return await meeting_handler.handle_reschedule_meeting(db, message_text, sender, reply_url, source)
        
        elif intent == "schedule_meeting":
            return await meeting_handler.handle_meeting_schedule(db, message_text, sender, reply_url, source)

        elif intent == "schedule_demo":
            return await demo_handler.handle_demo_schedule(db, message_text, sender, reply_url, source)

        elif "reschedule demo" in lowered_text or "demo reschedule" in lowered_text:
            return await demo_handler.handle_demo_reschedule(db, message_text, sender, reply_url, source)
            
        elif intent == "meeting_done":
            return await meeting_handler.handle_post_meeting_update(db, message_text, sender, reply_url, source)

        elif intent == "demo_done":
            return await demo_handler.handle_post_demo(db, message_text, sender, reply_url, source)

        elif intent == "reminder":
            return await reminder_handler.handle_set_reminder(db, message_text, sender, reply_url, source)

        elif intent == "reassign_task":
            return await reassignment_handler.handle_reassignment(db, message_text, sender, reply_url, source)

        elif "not interested" in lowered_text:
            company = parse_update_company(message_text)
            lead = get_lead_by_company(db, company)
            if not lead:
                return send_message(reply_url, sender, f"❌ Lead not found for '{company}'.", source)
            remark_match = re.search(r"(?:because|reason|remark)\s+(.*)", message_text, re.IGNORECASE)
            remark = remark_match.group(1).strip() if remark_match else "Not interested after initial contact."
            update_lead_status(db, lead.id, "Unqualified", updated_by=str(sender), remark=remark)
            return send_message(reply_url, sender, f"✅ Marked '{company}' as Unqualified. Remark: '{remark}'.", source)

        elif "not in our segment" in lowered_text:
            company = parse_update_company(message_text)
            lead = get_lead_by_company(db, company)
            if not lead:
                return send_message(reply_url, sender, f"❌ Lead not found for '{company}'.", source)
            update_lead_status(db, lead.id, "Not Our Segment", updated_by=str(sender))
            return send_message(reply_url, sender, f"📂 Marked '{company}' as 'Not Our Segment'.", source)
        
        else:
            fallback = (
                "🤖 I didn't understand that command. You can say things like:\n"
                "➡️ 'New lead ...'\n"
                "➡️ 'Log discussion for ...'\n"
                "➡️ 'Schedule meeting with ...'"
            )
            return send_message(reply_url, sender, fallback, source)

    except Exception as e:
        logger.error(f"❌ Exception in route_message: {e}", exc_info=True)
        if sender in pending_context:
            pending_context.pop(sender, None)
        return send_message(reply_url, sender, "❌ An internal error occurred.", source)

    finally:
        db.close()