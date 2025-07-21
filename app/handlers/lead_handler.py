# lead_handler.py
import logging
from sqlalchemy.orm import Session
from app.crud import (
    get_user_by_phone,
    get_user_by_name,
    get_lead_by_company,
    create_lead,
)
from app.message_sender import send_whatsapp_message, send_message, format_phone
from app.schemas import LeadCreate
from app.gpt_parser import parse_lead_info, parse_update_fields
from app.temp_store import temp_store

logger = logging.getLogger(__name__)

# --- CORRECTED LINE: Changed 'def' to 'async def' ---
async def handle_new_lead(db: Session, message_text: str, created_by: str, reply_url: str, source: str = "whatsapp"):
    try:
        parsed_data, polite_message = parse_lead_info(message_text)

        if isinstance(parsed_data, dict) and parsed_data.get("missing_fields"):
            response = send_message(reply_url, created_by, polite_message, source)
            if source.lower() == "app":
                return response
            return {"status": "error", "detail": polite_message}

        logger.info("🎯 Handling new lead with parsed data: %s", parsed_data)

        required_fields = ["company_name", "contact_name", "phone", "source", "assigned_to"]
        missing_fields = [field for field in required_fields if not parsed_data.get(field)]
        logger.info(f"🔍 Missing fields: {missing_fields}")
        if missing_fields:
            polite_msg = (
                "🙏 Please provide these required fields to create the lead:\n"
                "🏢 Company Name\n👤 Contact Person\n📞 Phone\n📲 Source\n👨‍💼 Assigned To (phone or name)"
            )
            response = send_message(reply_url, created_by, polite_msg, source)
            if source.lower() == "app":
                return response
            return {"status": "error", "detail": f"Missing field(s): {', '.join(missing_fields)}"}

        existing = get_lead_by_company(db, parsed_data["company_name"])
        if existing:
            response = send_message(reply_url, created_by, f"⚠️ Lead for '{parsed_data['company_name']}' already exists.", source)
            if source.lower() == "app":
                return response
            return {"status": "error", "detail": "Lead already exists"}

        assigned_to_input = parsed_data.get("assigned_to")
        assigned_user = None

        if assigned_to_input:
            assigned_to_cleaned = assigned_to_input.strip().lower()
            if assigned_to_cleaned.isdigit():
                assigned_user = get_user_by_phone(db, assigned_to_cleaned)
            else:
                assigned_user = get_user_by_name(db, assigned_to_cleaned)

        if not assigned_user:
            response = send_message(reply_url, created_by, f"❌ Couldn't find team member '{assigned_to_input}' in the system.", source)
            if source.lower() == "app":
                return response
            return {"status": "error", "detail": f"User '{assigned_to_input}' not found"}

        assigned_to = assigned_user.username

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
            status="New Lead",
            assigned_to=assigned_to,
            created_by=created_by,
        )

        created = create_lead(db, lead_data, created_by, assigned_to)

        creator_response = send_message(reply_url, created_by, f"✅ New lead created: {created.company_name}", source)
        
        # 📢 Notify assignee (only for WhatsApp, not for app)
        if assigned_user.usernumber and source.lower() != "app":
            send_whatsapp_message(
                reply_url,
                format_phone(assigned_user.usernumber),
                f"📢 You have been assigned a new lead:\n🏢 {created.company_name}\n👤 {created.contact_name}, 📞 {created.phone}"
            )

        # Return app response if source is app
        if source.lower() == "app":
            return creator_response
        
        return {"status": "success", "lead_id": created.id}

    except Exception as e:
        logger.error("❌ Error in handle_new_lead: %s", str(e), exc_info=True)
        response = send_message(reply_url, created_by, "❌ An error occurred while creating the lead", source)
        if source.lower() == "app":
            return response
        return {"status": "error", "detail": str(e)}

async def handle_update_lead(db: Session, message_text: str, sender: str, reply_url: str, company_name: str = None, source: str = "whatsapp"):
    

    try:
        update_fields = parse_update_fields(message_text)

        # Use company_name from context or memory
        company_name = company_name or update_fields.get("company_name") or temp_store.get(sender)
        if not company_name:
            response = send_message(reply_url, sender, "⚠️ Please mention the company name.")
            if source.lower() == "app":
                return response
            return {"status": "error", "message": "Missing company name."}

        lead = get_lead_by_company(db, company_name)
        if not lead:
            response = send_message(reply_url, sender, f"❌ No lead found for {company_name}")
            if source.lower() == "app":
                return response
            return {"status": "error", "message": f"Lead not found for {company_name}"}

        # Update matching fields
        updated_fields = []
        for field, value in update_fields.items():
            if hasattr(lead, field) and value:
                setattr(lead, field, value)
                updated_fields.append(field)

        if not updated_fields:
            response = send_message(reply_url, sender, "⚠️ No valid fields found to update.")
            if source.lower() == "app":
                return response
            return {"status": "error", "message": "No valid fields to update"}

        db.commit()

        # Remember company for future messages
        temp_store.set(sender, company_name)

        response = send_message(reply_url, sender, f"✅ Lead for '{company_name}' updated: {', '.join(updated_fields)}, Now schedule Demo for '{company_name}'")
        if source.lower() == "app":
                return response
        return {"status": "success", "message": "Lead updated successfully"}

    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error("Error updating lead: %s", str(e), exc_info=True)
        response = send_message(reply_url, sender, "❌ Something went wrong during update.")
        if source.lower() == "app":
                return response
        return {"status": "error", "detail": str(e)}