import logging
from sqlalchemy.orm import Session
from app.crud import (
    get_user_by_phone,
    get_user_by_name,
    get_lead_by_company,
    create_lead,
)
from app.message_sender import send_whatsapp_message, format_phone
from app.schemas import LeadCreate
from app.gpt_parser import parse_lead_info

logger = logging.getLogger(__name__)

def handle_new_lead(db: Session, message_text: str, created_by: str, reply_url: str):
    try:
        # 🔍 Parse message using GPT parser
        parsed_data, polite_message = parse_lead_info(message_text)

        # ❗ If parsing failed or missing fields
        if isinstance(parsed_data, dict) and parsed_data.get("missing_fields"):
            send_whatsapp_message(reply_url, created_by, polite_message)
            return {"status": "error", "detail": polite_message}

        logger.info("🎯 Handling new lead with parsed data: %s", parsed_data)

        # ✅ Required fields check
        required_fields = ["company_name", "contact_name", "phone", "source", "assigned_to"]
        missing_fields = [field for field in required_fields if not parsed_data.get(field)]
        logger.info(f"🔍 Missing fields: {missing_fields}")
        if missing_fields:
            polite_msg = (
                "🙏 Please provide these required fields to create the lead:\n"
                "🏢 Company Name\n👤 Contact Person\n📞 Phone\n📲 Source\n👨‍💼 Assigned To (phone or name)"
            )
            send_whatsapp_message(reply_url, created_by, polite_msg)
            return {"status": "error", "detail": f"Missing field(s): {', '.join(missing_fields)}"}

        # 🔁 Duplicate company check
        existing = get_lead_by_company(db, parsed_data["company_name"])
        if existing:
            send_whatsapp_message(reply_url, created_by, f"⚠️ Lead for '{parsed_data['company_name']}' already exists.")
            return {"status": "error", "detail": "Lead already exists"}

        # 👨‍💼 Resolve assigned_to (if it's name or phone, get user and use user.id)
        assigned_to_input = parsed_data.get("assigned_to")
        assigned_user = None

        if assigned_to_input:
            assigned_to_cleaned = assigned_to_input.strip().lower()
            if assigned_to_cleaned.isdigit():
                assigned_user = get_user_by_phone(db, assigned_to_cleaned)
            else:
                assigned_user = get_user_by_name(db, assigned_to_cleaned)

        if not assigned_user:
            send_whatsapp_message(reply_url, created_by, f"❌ Couldn't find team member '{assigned_to_input}' in the system.")
            return {"status": "error", "detail": f"User '{assigned_to_input}' not found"}

        assigned_to = assigned_user.username  # 👈 use username

        # 🧾 Prepare lead data with only required + optional fields
        lead_data = LeadCreate(
            company_name=parsed_data["company_name"],
            contact_name=parsed_data["contact_name"],
            phone=parsed_data["phone"],
            email=parsed_data.get("email"),
            address=parsed_data.get("address"),
            source=parsed_data["source"],
            segment=parsed_data.get("segment"),
            team_size=parsed_data.get("team_size"),
            remark=parsed_data.get("remark"),
            product=parsed_data.get("product"),
            city=parsed_data.get("city"),
            status="New Lead",  # ✅ Always set status to "New Lead"
            assigned_to=assigned_to,
            created_by=created_by,
        )

        # 💾 Create the lead in DB
        created = create_lead(db, lead_data, created_by, assigned_to)

        # ✅ Notify creator
        send_whatsapp_message(reply_url, created_by, f"✅ New lead created: {created.company_name}")

        # 📢 Notify assignee
        if assigned_user.usernumber:
            send_whatsapp_message(
                reply_url,
                format_phone(assigned_user.usernumber),
                f"📢 You have been assigned a new lead:\n🏢 {created.company_name}\n👤 {created.contact_name}, 📞 {created.phone}"
            )

        return {"status": "success", "lead_id": created.id}

    except Exception as e:
        logger.error("❌ Error in handle_new_lead: %s", str(e), exc_info=True)
        send_whatsapp_message(reply_url, created_by, "❌ An error occurred while creating the lead")
        return {"status": "error", "detail": str(e)}

# ✅ New: Update existing lead
async def handle_update_lead(db: Session, message_text: str, sender: str, reply_url: str, company_name: str):
    try:
        parsed_data, _ = parse_lead_info(message_text)

        lead = get_lead_by_company(db, company_name)
        if not lead:
            send_whatsapp_message(reply_url, sender, f"❌ No existing lead found for {company_name}")
            return {"status": "error", "message": "Lead not found"}

        # 🛠 Update only if fields are present
        lead.address = parsed_data.get("address") or lead.address
        lead.segment = parsed_data.get("segment") or lead.segment
        lead.team_size = parsed_data.get("team_size") or lead.team_size
        lead.email = parsed_data.get("email") or lead.email
        lead.remark = parsed_data.get("remark") or lead.remark

        db.commit()
        send_whatsapp_message(reply_url, sender, f"✅ Lead '{company_name}' updated successfully.")
        return {"status": "success"}

    except Exception as e:
        logger.error("❌ Error in handle_update_lead: %s", str(e), exc_info=True)
        send_whatsapp_message(reply_url, sender, f"❌ Failed to update lead for '{company_name}'")
        return {"status": "error", "detail": str(e)}
