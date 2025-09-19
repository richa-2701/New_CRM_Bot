# lead_handler.py
import logging
from sqlalchemy.orm import Session
from app.crud import (
    get_user_by_phone,
    get_user_by_name,
    get_lead_by_company,
    save_lead,
    create_activity_log
)
from app.message_sender import send_whatsapp_message, send_message, format_phone 
from app.schemas import LeadCreate, ContactCreate, ActivityLogCreate
from app.gpt_parser import parse_lead_info, parse_update_fields
from app.temp_store import temp_store
from datetime import datetime

logger = logging.getLogger(__name__)

async def handle_new_lead(db: Session, message_text: str, created_by: str, reply_url: str, source: str = "whatsapp"):
    try:
        parsed_data, polite_message = parse_lead_info(message_text)
        
        if not parsed_data or "company_name" not in parsed_data or parsed_data.get("missing_fields"):
            return send_message(number=created_by, message=polite_message, source=source)

        logger.info("🎯 Handling new lead with parsed data: %s", parsed_data)

        required_for_lead_creation = ["company_name", "phone", "assigned_to", "source"]
        if not all(parsed_data.get(field) for field in required_for_lead_creation):
            missing = [f for f in required_for_lead_creation if not parsed_data.get(f)]
            return send_message(number=created_by, message=f"🙏 Please provide all required fields: {', '.join(missing).replace('_', ' ').title()}.", source=source)

        existing = get_lead_by_company(db, parsed_data["company_name"])
        if existing:
            return send_message(number=created_by, message=f"⚠️ Leaad for '{parsed_data['company_name']}' already exists.", source=source)

        assignee_user = get_user_by_name(db, parsed_data["assigned_to"])
        if not assignee_user:
            return send_message(number=created_by, message=f"❌ Assigned user '{parsed_data['assigned_to']}' not found. Please provide a valid assignee.", source=source)

        contacts_to_create = []
        if parsed_data.get("contact_name") or parsed_data.get("phone"):
            contacts_to_create.append(ContactCreate(
                contact_name=parsed_data.get("contact_name"),
                phone=parsed_data.get("phone"),
                email=parsed_data.get("email")
            ))
        else:
            if parsed_data.get("phone"):
                 contacts_to_create.append(ContactCreate(
                    contact_name=f"Primary Contact for {parsed_data.get('company_name')}",
                    phone=parsed_data.get("phone"),
                    email=parsed_data.get("email")
                 ))
            pass

        lead_data_for_creation = LeadCreate(
            company_name=parsed_data.get("company_name"),
            source=parsed_data.get("source", "whatsapp"),
            created_by=str(created_by),
            assigned_to=assignee_user.username,
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
            lead_type=parsed_data.get("lead_type"),
            contacts=contacts_to_create
        )
        
        created_lead = save_lead(
            db=db,
            lead_data=lead_data_for_creation
        )
        
        create_activity_log(db, ActivityLogCreate(
            lead_id=created_lead.id,
            phase="New Lead",
            details=f"New lead '{created_lead.company_name}' created by {created_by} and assigned to {created_lead.assigned_to}.",
            activity_type="Lead Creation"
        ))

        # --- MODIFIED: Send assignee notification if assignee has a usernumber ---
        if assignee_user.usernumber: # Removed the check: != str(created_by)
            contact_name_for_msg = created_lead.contacts[0].contact_name if created_lead.contacts and created_lead.contacts[0].contact_name else 'N/A'
            contact_phone_for_msg = created_lead.contacts[0].phone if created_lead.contacts and created_lead.contacts[0].phone else 'N/A'

            notification_msg = (
                f"📢 You have been assigned a new lead:\n"
                f"🏢 Company: *{created_lead.company_name}*\n"
                f"👤 Contact: {contact_name_for_msg}\n"
                f"📱 Phone: {contact_phone_for_msg}\n"
                f"📍 Source: {created_lead.source}"
            )
            
            logger.info(f"Attempting to send WhatsApp notification to assignee: Usernumber={assignee_user.usernumber}, Message='{notification_msg}'")
            send_whatsapp_message(number=assignee_user.usernumber, message=notification_msg)
            logger.info(f"Sent new lead notification to assignee {assignee_user.username} ({assignee_user.usernumber})")
        else:
            logger.warning(f"Skipping assignee WhatsApp notification: Assignee '{assignee_user.username}' has no usernumber configured.")


        confirmation_msg = f"✅ New lead *{created_lead.company_name}* created and assigned to *{created_lead.assigned_to}*."
        
        return send_message(number=created_by, message=confirmation_msg, source=source)

    except ValueError as e:
        logger.error(f"❌ Lead creation failed: {e}")
        db.rollback()
        return send_message(number=created_by, message=f"❌ Failed to create lead: {e}", source=source)
    except Exception as e:
        logger.error(f"❌ An unexpected error occurred during lead creation: {e}", exc_info=True)
        db.rollback()
        return send_message(number=created_by, message="❌ An internal error occurred while creating the lead.", source=source)


async def handle_update_lead(db: Session, message_text: str, sender: str, reply_url: str, company_name: str = None, source: str = "whatsapp"):
    try:
        update_fields, _ = parse_update_fields(message_text)

        company_name = company_name or update_fields.get("company_name") or temp_store.get(sender)
        if not company_name:
            response_msg = "⚠️ Please mention the company name to update."
            return send_message(number=sender, message=response_msg, source=source)

        lead = get_lead_by_company(db, company_name)
        if not lead:
            response_msg = f"❌ No lead found for {company_name}"
            return send_message(number=sender, message=response_msg, source=source)

        updated_fields = []
        for field, value in update_fields.items():
            if hasattr(lead, field) and value:
                setattr(lead, field, value)
                updated_fields.append(field)

        if not updated_fields:
            response_msg = "⚠️ No valid fields found in your message to update."
            return send_message(number=sender, message=response_msg, source=source)

        db.commit()

        temp_store.set(sender, company_name)
        confirmation_message = f"✅ Lead for '{company_name}' updated: {', '.join(updated_fields)}. Now schedule Demo for '{company_name}'"
        return send_message(number=sender, message=confirmation_message, source=source)

    except Exception as e:
        logger.error("Error updating lead: %s", str(e), exc_info=True)
        return send_message(number=sender, message="❌ Something went wrong during the update.", source=source)