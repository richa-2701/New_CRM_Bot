# lead_handler.py
import logging
from sqlalchemy.orm import Session
from app.crud import (
    get_user_by_phone,
    get_user_by_name,
    get_lead_by_company,
    save_lead
)
from app.message_sender import send_whatsapp_message, send_message, format_phone
from app.schemas import LeadCreate, ContactCreate
from app.gpt_parser import parse_lead_info, parse_update_fields
from app.temp_store import temp_store

logger = logging.getLogger(__name__)

async def handle_new_lead(db: Session, message_text: str, created_by: str, reply_url: str, source: str = "whatsapp"):
    try:
        parsed_data, polite_message = parse_lead_info(message_text)

        if not parsed_data or "company_name" not in parsed_data:
            return send_message(reply_url, created_by, polite_message, source)

        logger.info("🎯 Handling new lead with parsed data: %s", parsed_data)

        required_fields = ["company_name", "contact_name", "phone", "assigned_to"]
        if not all(parsed_data.get(field) for field in required_fields):
            return send_message(reply_url, created_by, "🙏 Please provide Company, Contact, Phone, and Assignee.", source)

        existing = get_lead_by_company(db, parsed_data["company_name"])
        if existing:
            return send_message(reply_url, created_by, f"⚠️ Lead for '{parsed_data['company_name']}' already exists.", source)

        # --- CHANGE 2: Construct the data in the new, correct format ---
        # First, create the contact object
        contact_payload = ContactCreate(
            contact_name=parsed_data.get("contact_name"),
            phone=parsed_data.get("phone"),
            email=parsed_data.get("email") # This will be None if not found, which is correct
        )

        # Now, create the lead object, embedding the contact inside the 'contacts' list
        lead_data_for_creation = LeadCreate(
            company_name=parsed_data.get("company_name"),
            source=parsed_data.get("source", "whatsapp"),
            created_by=str(created_by),
            assigned_to=parsed_data.get("assigned_to"),
            contacts=[contact_payload], # Pass the contact payload inside a list
            email=parsed_data.get("email"),
            address=parsed_data.get("address"),
            team_size=parsed_data.get("team_size"),
            segment=parsed_data.get("segment"),
            remark=parsed_data.get("remark"),
            product=parsed_data.get("product"),
            phone_2=parsed_data.get("phone_2"),
            turnover=parsed_data.get("turnover"),
            current_system=parsed_data.get("current_system"),
            machine_specification=parsed_data.get("machine_specification"),
            challenges=parsed_data.get("challenges"),
            lead_type=parsed_data.get("lead_type")
        )
        # 

        # Call the corrected `save_lead` function which now only takes one argument.
        created_lead = save_lead(
            db=db,
            lead_data=lead_data_for_creation
        )
        
        assignee_user = get_user_by_name(db, created_lead.assigned_to)
        
        if assignee_user and assignee_user.usernumber and assignee_user.usernumber != str(created_by):
            assignee_message = f"📢 You have been assigned a new lead:\n🏢 {created_lead.company_name}\n👤 {lead_data_for_creation.initial_contact_name}, 📞 {lead_data_for_creation.initial_contact_phone}"
            send_whatsapp_message(reply_url, format_phone(assignee_user.usernumber), assignee_message)

        confirmation_message = f"✅ New lead created: {created_lead.company_name}"
        return send_message(reply_url, created_by, confirmation_message, source)

    except Exception as e:
        logger.error("❌ Error in handle_new_lead: %s", str(e), exc_info=True)
        db.rollback()
        return send_message(reply_url, created_by, "❌ An error occurred while creating the lead.", source)


async def handle_update_lead(db: Session, message_text: str, sender: str, reply_url: str, company_name: str = None, source: str = "whatsapp"):
    try:
        update_fields, _ = parse_update_fields(message_text)

        company_name = company_name or update_fields.get("company_name") or temp_store.get(sender)
        if not company_name:
            response_msg = "⚠️ Please mention the company name to update."
            return send_message(reply_url, sender, response_msg, source)

        lead = get_lead_by_company(db, company_name)
        if not lead:
            response_msg = f"❌ No lead found for {company_name}"
            return send_message(reply_url, sender, response_msg, source)

        updated_fields = []
        for field, value in update_fields.items():
            if hasattr(lead, field) and value:
                setattr(lead, field, value)
                updated_fields.append(field)

        if not updated_fields:
            response_msg = "⚠️ No valid fields found in your message to update."
            return send_message(reply_url, sender, response_msg, source)

        db.commit()

        temp_store.set(sender, company_name)
        confirmation_message = f"✅ Lead for '{company_name}' updated: {', '.join(updated_fields)}. Now schedule Demo for '{company_name}'"
        return send_message(reply_url, sender, confirmation_message, source)

    except Exception as e:
        logger.error("Error updating lead: %s", str(e), exc_info=True)
        return send_message(reply_url, sender, "❌ Something went wrong during the update.", source)