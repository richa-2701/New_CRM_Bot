import re
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import dateparser

from app.models import Lead
from app.crud import get_lead_by_company, create_event
from app.reminders import schedule_reminder
from app.schemas import EventCreate
from app.message_sender import send_whatsapp_message, format_phone
from app.db import get_db

async def handle_qualification(msg_text: str, sender: str, reply_url: str):
    db: Session = next(get_db())

    # ✅ Extract company name after "qualified for"
    company_match = re.search(r"qualified\s+for\s+(.+?)(?:,| schedule| assign to|$)", msg_text, re.IGNORECASE)
    if not company_match:
        send_whatsapp_message(reply_url, sender, "⚠️ Couldn't find company name in qualification message.")
        return

    company_name = company_match.group(1).strip()

    # ✅ Extract meeting time after "schedule meeting on ..."
    time_match = re.search(r"schedule\s+meeting\s+on\s+(.+?)(?: assign to|$)", msg_text, re.IGNORECASE)
    custom_dt = None
    if time_match:
        parsed = dateparser.parse(time_match.group(1), settings={'PREFER_DATES_FROM': 'future'})
        if parsed:
            custom_dt = parsed

    # ✅ Extract assignee after "assign to"
    assignee_match = re.search(r"assign\s+to\s+([a-zA-Z0-9@.+_ ]+)", msg_text, re.IGNORECASE)
    assignee = assignee_match.group(1).strip() if assignee_match else None

    # 🔍 Lookup lead
    lead = get_lead_by_company(db, company_name)
    if not lead:
        send_whatsapp_message(reply_url, sender, f"❌ No lead found with company: {company_name}")
        return

    # ✅ Use existing assignee if not provided
    assigned_to = assignee if assignee else lead.assigned_to

    # ✅ Update status and assignment
    lead.status = "qualified"
    lead.assigned_to = assigned_to
    db.commit()

    # 🕒 Meeting time: use parsed or default to +1 hour
    event_start = custom_dt if custom_dt else datetime.now() + timedelta(hours=1)
    event_end = event_start + timedelta(minutes=20)

    # 📅 Create meeting event
    event = EventCreate(
        lead_id=lead.id,
        assigned_to=assigned_to,
        event_type="4 Phase Meeting",
        event_time=event_start,
        event_end_time=event_end,
        created_by=sender,
        remark=f"4 Phase Meeting for {company_name}"
    )
    create_event(db, event)

    # ⏰ Schedule reminder
    schedule_reminder(
        db,
        lead_id=lead.id,
        assigned_to=assigned_to,
        message=f"Reminder: 4 Phase Meeting for {company_name} scheduled at {event_start.strftime('%I:%M %p')}",
        remind_at=event_start - timedelta(days=1)
    )

    # ✅ Confirm to sender
    send_whatsapp_message(
        reply_url,
        sender,
        f"✅ Lead '{company_name}' marked as qualified.\n📅 4 Phase Meeting scheduled on {event_start.strftime('%d %b %Y at %I:%M %p')}."
    )

    # 📤 Notify assignee
    if assigned_to:
        send_whatsapp_message(
            reply_url,
            format_phone(assigned_to),
            f"📢 You have a 4 Phase Meeting assigned for lead:\n🏢 {company_name}\n📅 {event_start.strftime('%d %b %Y')} at {event_start.strftime('%I:%M %p')}"
        )
