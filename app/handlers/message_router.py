# message_router.py

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
    feedback_handler,
    reassignment_handler,
    reminder_handler,
)
from app.temp_store import temp_store  # ✅ Context store

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

async def route_message(sender: str, message_text: str, reply_url: str):
    db: Session = SessionLocal()
    lowered_text = message_text.lower().strip()

    try:
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
                "👤 Contact Person Name\n"
                "📱 Phone Number\n"
                "📍 Source\n"
                "👨‍💼 Assigned To (Name or Phone)\n\n"
                "🗒️ Example:\n"
                "'There is a lead from ABC Pvt Ltd, contact is Ramesh (9876543210), Source Referral, interested in inventory software, assign to Banwari.'"
                "✅ Format 2: Comma-Separated \n ABC Pvt Ltd, Ramesh, 9876543210, Jaipur, Inventory Software, Banwari'"
            )
            send_whatsapp_message(reply_url, sender, polite_msg)
            return {"status": "prompted_for_lead"}

        recent_company = temp_store.get(sender)  # ✅ Check context for update
        if intent == "new_lead" and recent_company:
            return await lead_handler.handle_update_lead(
                db=db,
                message_text=message_text,
                sender=sender,
                reply_url=reply_url,
                company_name=recent_company
            )

        if intent == "new_lead":
            return await lead_handler.handle_new_lead(
                db=db,
                message_text=message_text,
                created_by=sender,
                reply_url=reply_url
            )

        if intent == "qualify_lead":
            return await qualification_handler.handle_qualification(message_text, sender, reply_url)

        elif "reschedule meeting" in lowered_text:
            return await meeting_handler.handle_reschedule_meeting(db, message_text, sender, reply_url)

        elif intent == "schedule_meeting":
            return await meeting_handler.handle_meeting_schedule(db, message_text, sender, reply_url)

        elif intent == "schedule_demo":
            return await demo_handler.handle_demo_schedule(db, message_text, sender, reply_url)

        elif "reschedule demo" in lowered_text or "demo reschedule" in lowered_text:
            return await demo_handler.handle_demo_reschedule(db, message_text, sender, reply_url)

        elif "meeting done" in lowered_text or "meeting is done" in lowered_text:
            company = extract_company_name(message_text)
            if not company:
                send_whatsapp_message(reply_url, sender, "⚠️ Please include the company name in your message.")
                return {"status": "error", "message": "Company name missing"}
            return await meeting_handler.handle_post_meeting_update(db, message_text, sender, reply_url)

        elif intent == "demo_done":
            return await demo_handler.handle_post_demo(db, message_text, sender, reply_url)

        elif intent == "feedback":
            company_name = extract_company_name(message_text)
            return await feedback_handler.handle_feedback(db, company_name, message_text, sender, reply_url)

        elif intent == "reminder":
            return await reminder_handler.handle_set_reminder(db, message_text, sender, reply_url)

        elif intent == "reassign_task":
            return await reassignment_handler.handle_reassignment(db, message_text, sender, reply_url)

        elif "not interested" in lowered_text:
            company = extract_company_name(message_text)
            remark_match = re.search(r"(?:because|reason|remark)\s+(.*)", message_text, re.IGNORECASE)
            remark = remark_match.group(1).strip() if remark_match else "Not interested after initial contact."
            update_lead_status(db, company, "Unqualified", remark=remark)
            send_whatsapp_message(reply_url, sender, f"✅ Marked '{company}' as Unqualified. Remark: '{remark}'.")
            return {"status": "success"}

        elif "not in our segment" in lowered_text:
            company = extract_company_name(message_text)
            update_lead_status(db, company, "Not Our Segment")
            send_whatsapp_message(reply_url, sender, f"📂 Marked '{company}' as 'Not Our Segment'.")
            return {"status": "success"}

        else:
            fallback = (
                "🤖 I didn't understand that. You can say:\n"
                "'New lead from ABC, contact is Ramesh 98765..., city Jaipur, assign to Banwari.'"
            )
            send_whatsapp_message(reply_url, sender, fallback)
            return {"status": "unhandled"}

    except Exception as e:
        logger.error(f"❌ Exception in route_message: {e}", exc_info=True)
        send_whatsapp_message(reply_url, sender, "❌ Internal error occurred.")
        return {"status": "error", "detail": str(e)}

    finally:
        db.close()
