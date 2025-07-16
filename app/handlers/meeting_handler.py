import re
from datetime import datetime
from sqlalchemy.orm import Session
import dateparser
import logging

from app.models import Lead, Event, Demo
from app.crud import get_lead_by_company, create_event, get_user_by_phone, get_user_by_name
from app.schemas import EventCreate
from app.message_sender import send_whatsapp_message

logger = logging.getLogger(__name__)


def extract_details_for_event(text: str):
    company_name, assigned_to, meeting_time_str = None, None, None
    match = re.search(
        r"schedule\s+meeting\s+with\s+(.+?)\s+(?:for|assigned\s+to)\s+(.+?)\s+(?:on|at)\s+(.+)",
        text, re.IGNORECASE
    )
    if match:
        company_name = match.group(1).strip()
        assigned_to = match.group(2).strip()
        meeting_time_str = match.group(3).strip()
    return company_name, assigned_to, meeting_time_str


async def handle_meeting_schedule(db: Session, message_text: str, sender_phone: str, reply_url: str):
    try:
        company_name, assigned_to_name, meeting_time_str = extract_details_for_event(message_text)

        if not all([company_name, assigned_to_name, meeting_time_str]):
            error_msg = '⚠️ Invalid format. Use: "Schedule meeting with [Company Name] assigned to [Person Name] on [Date and Time]"'
            send_whatsapp_message(reply_url, sender_phone, error_msg)
            return {"status": "error", "message": "Invalid schedule format"}

        lead = get_lead_by_company(db, company_name)
        if not lead:
            send_whatsapp_message(reply_url, sender_phone, f"❌ Lead for '{company_name}' not found.")
            return {"status": "error", "message": "Lead not found"}

        meeting_dt = dateparser.parse(meeting_time_str, settings={'PREFER_DATES_FROM': 'future'})
        if not meeting_dt:
            send_whatsapp_message(reply_url, sender_phone, f"❌ Could not understand the date/time: '{meeting_time_str}'")
            return {"status": "error", "message": "Invalid datetime"}

        event_data = EventCreate(
            lead_id=lead.id,
            assigned_to=assigned_to_name.title(),
            event_type="Meeting",
            event_time=meeting_dt,
            created_by=sender_phone,
            remark=f"Scheduled via WhatsApp by {sender_phone}"
        )

        new_event = create_event(db, event=event_data)
        logger.info(f"✅ Meeting event created with ID: {new_event.id} for lead: {lead.company_name}")

        creator_msg = f"✅ Meeting scheduled for '{lead.company_name}' with {assigned_to_name.title()} on {meeting_dt.strftime('%A, %b %d at %I:%M %p')}."
        send_whatsapp_message(reply_url, sender_phone, creator_msg)

        return {"status": "success"}

    except Exception as e:
        logger.error(f"❌ Error in handle_meeting_schedule: {e}", exc_info=True)
        send_whatsapp_message(reply_url, sender_phone, "❌ An internal error occurred while scheduling the meeting.")
        return {"status": "error", "details": str(e)}


# ✅ Post-meeting update and check for missing lead fields

def extract_company_name_from_meeting_update(msg_text: str) -> str:
    match = re.search(r"meeting done for (.+?)(?:\.|,| is| they|$)", msg_text, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def extract_remark_from_meeting_update(msg_text: str) -> str:
    match = re.search(r"(they .*|remark[:\-]?\s*.+)", msg_text, re.IGNORECASE)
    return match.group(1).strip().lstrip("Remark:").strip() if match else "No remark provided."


async def handle_post_meeting_update(db: Session, msg_text: str, sender: str, reply_url: str):
    company_name = extract_company_name_from_meeting_update(msg_text)
    remark = extract_remark_from_meeting_update(msg_text)

    lead = get_lead_by_company(db, company_name)
    if not lead:
        send_whatsapp_message(reply_url, sender, f"❌ Lead not found for company: {company_name}")
        return {"status": "error", "message": "Company not found"}

    meeting_event = db.query(Event).filter(
        Event.lead_id == lead.id,
        Event.event_type == "Meeting"
    ).order_by(Event.event_time.desc()).first()

    if not meeting_event:
        send_whatsapp_message(reply_url, sender, f"⚠️ No meeting found for {company_name}")
        return {"status": "error", "message": "No meeting found"}

    meeting_event.status = "done"
    meeting_event.remark = remark
    db.commit()

    send_whatsapp_message(reply_url, sender,
        f"✅ Meeting marked done for {company_name}.\n📝 Remark: {remark}"
    )

    # ✅ Check for missing optional fields
    missing_fields = []
    if not lead.address:
        missing_fields.append("Address")
    if not lead.segment:
        missing_fields.append("Segment")
    if not lead.team_size:
        missing_fields.append("Team Size")
    if not lead.email:
        missing_fields.append("Email")
    if not lead.remarks:
        missing_fields.append("Remark")

    if missing_fields:
        ask_msg = (
            f"📝 Thank you! 4-Phase meeting completed for *{company_name}*.\n"
            f"Please provide the following missing details:\n👉 " +
            ", ".join(missing_fields)
        )
        send_whatsapp_message(reply_url, sender, ask_msg)

    return {"status": "success", "message": "Meeting marked done"}



async def handle_reschedule_meeting(db: Session, msg_text: str, sender: str, reply_url: str):
    try:
        # Step 1: Extract company and new datetime
        match = re.search(r"reschedule\s+meeting\s+for\s+(.+?)\s+on\s+(.+)", msg_text, re.IGNORECASE)
        if not match:
            send_whatsapp_message(reply_url, sender,
                "⚠️ Invalid format. Use: 'Reschedule meeting for [Company Name] on [Date and Time]'")
            return {"status": "error", "message": "Invalid reschedule format"}

        company_name = match.group(1).strip()
        new_time_str = match.group(2).strip()

        # Step 2: Parse datetime
        new_datetime = dateparser.parse(new_time_str, settings={'PREFER_DATES_FROM': 'future'})
        if not new_datetime:
            send_whatsapp_message(reply_url, sender,
                f"❌ Couldn't parse new meeting time: '{new_time_str}'")
            return {"status": "error", "message": "Invalid datetime"}

        # Step 3: Find lead
        lead = get_lead_by_company(db, company_name)
        if not lead:
            send_whatsapp_message(reply_url, sender,
                f"❌ Lead not found for company: {company_name}")
            return {"status": "error", "message": "Company not found"}

        # Step 4: Find the latest scheduled Meeting (include variants)
        event = db.query(Event).filter(
            Event.lead_id == lead.id,
            Event.event_type.in_(["Meeting", "4 Phase Meeting"])  # Accept both types
        ).order_by(Event.event_time.desc()).first()

        if not event:
            send_whatsapp_message(reply_url, sender,
                f"⚠️ No existing meeting found for {company_name}")
            return {"status": "error", "message": "No existing meeting"}

        # Step 5: Reschedule
        event.event_time = new_datetime
        event.remark = f"Rescheduled via WhatsApp by {sender}"

        # Optional: update updated_at if you have that field in Event
        if hasattr(event, "updated_at"):
            event.updated_at = datetime.now()

        db.commit()

        # Notify the user
        send_whatsapp_message(reply_url, sender,
            f"✅ Meeting for *{company_name}* rescheduled to {new_datetime.strftime('%d %b %Y at %I:%M %p')}.")

        # Notify the assignee if exists
        if event.assigned_to:
            send_whatsapp_message(reply_url, event.assigned_to,
                f"📢 Meeting for *{company_name}* has been rescheduled.\n📅 New Time: {new_datetime.strftime('%d %b %Y at %I:%M %p')}")

        return {"status": "success"}

    except Exception as e:
        logging.exception("❌ Exception during meeting reschedule")
        send_whatsapp_message(reply_url, sender, "❌ Internal error while rescheduling meeting.")
        return {"status": "error", "details": str(e)}
