# app/handlers/message_router.py
import re
import logging
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.gpt_parser import parse_intent_and_fields, parse_lead_info, parse_update_company
from app.message_sender import send_whatsapp_message,send_message
# --- MODIFIED: Import `get_lead_by_company` ---
from app.crud import update_lead_status, get_user_by_name, get_lead_by_company
from app.handlers import (
    lead_handler,
    qualification_handler,
    meeting_handler,
    demo_handler,
    reassignment_handler,
    reminder_handler,
    activity_handler,
)
from app.temp_store import temp_store
# Import the context dict directly to check its state
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
        # 🔁 CRITICAL: First, check if there's a pending multi-step action for this user.
        if sender in pending_context:
            context = pending_context[sender]
            logger.info(f"Found pending context for {sender}: {context}")
            
            # --- START OF ALL CONTEXT-BASED ROUTING ---
            
            # --- START OF ALL CONTEXT-BASED ROUTING ---
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
                logger.info(f"Routing message from {sender} to {context.get("intent")} handler.")
                return await handler(
                    db=db,
                    msg_text=message_text,
                    sender=sender,
                    reply_url=reply_url,
                    source=source
                )
            # --- END OF ALL CONTEXT-BASED ROUTING ---

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
            response = send_message(reply_url, sender, polite_msg, source)
            if source.lower() == "app":
                return response
            return {"status": "prompted_for_lead"}
        
        if "add activity for" in lowered_text:
            return await activity_handler.handle_add_activity(db, message_text, sender, reply_url, source)
        
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
            
        elif intent == "meeting_done":
            return await meeting_handler.handle_post_meeting_update(db, message_text, sender, reply_url)

        elif intent == "demo_done":
            return await demo_handler.handle_post_demo(db, message_text, sender, reply_url)

        elif intent == "reminder":
            return await reminder_handler.handle_set_reminder(db, message_text, sender, reply_url)

        elif intent == "reassign_task":
            return await reassignment_handler.handle_reassignment(db, message_text, sender, reply_url)

        # --- MODIFIED: Refactored to use centralized status update ---
        elif "not interested" in lowered_text:
            company = parse_update_company(message_text)
            lead = get_lead_by_company(db, company)
            if not lead:
                response = send_message(reply_url, sender, f"❌ Lead not found for '{company}'.", source)
                if source.lower() == "app": return response
                return {"status": "error", "message": "Lead not found"}

            remark_match = re.search(r"(?:because|reason|remark)\s+(.*)", message_text, re.IGNORECASE)
            remark = remark_match.group(1).strip() if remark_match else "Not interested after initial contact."
            
            update_lead_status(db, lead.id, "Unqualified", updated_by=sender, remark=remark)
            
            response = send_message(reply_url, sender, f"✅ Marked '{company}' as Unqualified. Remark: '{remark}'.", source)
            if source.lower() == "app":
                return response
            return {"status": "success"}

        elif "not in our segment" in lowered_text:
            company = parse_update_company(message_text)
            lead = get_lead_by_company(db, company)
            if not lead:
                response = send_message(reply_url, sender, f"❌ Lead not found for '{company}'.", source)
                if source.lower() == "app": return response
                return {"status": "error", "message": "Lead not found"}
            
            update_lead_status(db, lead.id, "Not Our Segment", updated_by=sender)
            
            response = send_message(reply_url, sender, f"📂 Marked '{company}' as 'Not Our Segment'.", source)
            if source.lower() == "app":
                return response
            return {"status": "success"}
        
        else:
            # Fallback message is now more accurate since conversational replies are handled
            # before this point.
            fallback = (
                "🤖 I didn't understand that command. You can say things like:\n"
                "➡️ 'New lead ...'\n"
                "➡️ 'Add activity for ...'\n"
                "➡️ 'Schedule meeting with ...'"
            )
            response = send_message(reply_url, sender, fallback, source)
            if source.lower() == "app":
                return response
            return {"status": "unhandled"}

    except Exception as e:
        logger.error(f"❌ Exception in route_message: {e}", exc_info=True)
        # On a critical failure, clear the user's context to prevent them from being stuck.
        if sender in pending_context:
            pending_context.pop(sender, None)
        response = send_message(reply_url, sender, "❌ Internal error occurred.", source)
        if source.lower() == "app":
            return response
        return {"status": "error", "detail": str(e)}

    finally:
        db.close()