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

async def handle_new_lead(db: Session, message_text: str, created_by: str, reply_url: str, source: str = "whatsapp"):
    try:
        parsed_data, polite_message = parse_lead_info(message_text)

        if isinstance(parsed_data, dict) and parsed_data.get("missing_fields"):
            return send_message(reply_url, created_by, polite_message, source)

        logger.info("🎯 Handling new lead with parsed data: %s", parsed_data)

        required_fields = ["company_name", "contact_name", "phone", "source", "assigned_to"]
        missing_fields = [field for field in required_fields if not parsed_data.get(field)]
        if missing_fields:
            polite_msg = (
                "🙏 Please provide these required fields to create the lead:\n"
                "🏢 Company Name\n👤 Contact Person\n📞 Phone\n📲 Source\n👨‍💼 Assigned To (phone or name)"
            )
            return send_message(reply_url, created_by, polite_msg, source)

        existing = get_lead_by_company(db, parsed_data["company_name"])
        if existing:
            return send_message(reply_url, created_by, f"⚠️ Lead for '{parsed_data['company_name']}' already exists.", source)

        assigned_to_input = parsed_data.get("assigned_to")
        assigned_user = None
        if assigned_to_input:
            # Safely convert to string before checking if it's a digit
            if str(assigned_to_input).strip().isdigit():
                assigned_user = get_user_by_phone(db, assigned_to_input)
            else:
                assigned_user = get_user_by_name(db, assigned_to_input)

        if not assigned_user:
            return send_message(reply_url, created_by, f"❌ Couldn't find team member '{assigned_to_input}' in the system.", source)
        
        # --- THIS IS THE CORRECTED CODE BLOCK ---
        # Update the parsed_data dictionary with validated and system-generated values.
        # Crucially, we convert `created_by` to a string to match the Pydantic schema.
        parsed_data["assigned_to"] = assigned_user.username
        parsed_data["created_by"] = str(created_by)

        # 2. Create the LeadCreate object by unpacking the dictionary.
        # This automatically includes ALL fields parsed by GPT (turnover, challenges, etc.).
        # We also need to remove fields that are not part of the LeadCreate schema if they exist.
        
        # Ensure only fields from LeadCreate schema are passed
        valid_lead_fields = LeadCreate.model_fields.keys()
        final_lead_data = {k: v for k, v in parsed_data.items() if k in valid_lead_fields}

        lead_data = LeadCreate(**final_lead_data)

        # 3. Call the CRUD function with the fully populated object.
        # The `create_lead` function now receives `assigned_name` and `assigned_number`
        # for user lookup, so we can simplify the call.
        created = create_lead(
            db=db,
            lead=lead_data,
            created_by=created_by,
            assigned_name=assigned_user.username # Pass the validated username
        )
        # --- END OF THE FIX ---

        # The rest of the notification logic remains the same.
        if assigned_user.usernumber:
            assignee_message = f"📢 You have been assigned a new lead:\n🏢 {created.company_name}\n👤 {created.contact_name}, 📞 {created.phone}"
            send_whatsapp_message(
                reply_url,
                format_phone(assigned_user.usernumber),
                assignee_message
            )

        confirmation_message = f"✅ New lead created: {created.company_name}"
        return send_message(reply_url, created_by, confirmation_message, source)

    except Exception as e:
        logger.error("❌ Error in handle_new_lead: %s", str(e), exc_info=True)
        return send_message(reply_url, created_by, "❌ An error occurred while creating the lead", source)



async def handle_update_lead(db: Session, message_text: str, sender: str, reply_url: str, company_name: str = None, source: str = "whatsapp"):
    try:
        update_fields, _ = parse_update_fields(message_text)

        # Use company_name from context or memory
        company_name = company_name or update_fields.get("company_name") or temp_store.get(sender)
        if not company_name:
            response_msg = "⚠️ Please mention the company name to update."
            return send_message(reply_url, sender, response_msg, source)

        lead = get_lead_by_company(db, company_name)
        if not lead:
            response_msg = f"❌ No lead found for {company_name}"
            return send_message(reply_url, sender, response_msg, source)

        # Update matching fields
        updated_fields = []
        for field, value in update_fields.items():
            if hasattr(lead, field) and value:
                setattr(lead, field, value)
                updated_fields.append(field)

        if not updated_fields:
            response_msg = "⚠️ No valid fields found in your message to update."
            return send_message(reply_url, sender, response_msg, source)

        db.commit()

        # Remember company for future messages
        temp_store.set(sender, company_name)

        confirmation_message = f"✅ Lead for '{company_name}' updated: {', '.join(updated_fields)}, Now schedule Demo for '{company_name}'"

        # Simply return the result of send_message; it handles both sources correctly.
        return send_message(reply_url, sender, confirmation_message, source)

    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error("Error updating lead: %s", str(e), exc_info=True)
        return send_message(reply_url, sender, "❌ Something went wrong during the update.", source)