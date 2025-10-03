# app/webhook.py
from fastapi import APIRouter, Request, Response, status,HTTPException,Depends,UploadFile, File, Form
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.handlers.message_router import route_message
import logging
from fastapi.responses import StreamingResponse
import httpx
import shutil
import hashlib
import pandas as pd
import uuid
from app import schemas
from ics import Calendar, Event as ICSEvent
from app.models import User
import pytz
import os
from pydantic import BaseModel
import re
from sqlalchemy import or_, and_
from countryinfo import CountryInfo
import io
from fastapi.responses import FileResponse
from typing import Optional, List
from app import models
from app.models import Lead, Event, Demo, Reminder, Client, ClientContact, LeadAttachment, ProposalSent
from app.schemas import (
    LeadResponse, ScheduleActivityWeb, ReminderCreate, UserCreate, UserLogin, UserResponse, TaskOut,
    ActivityLogOut, HistoryItemOut, UserPasswordChange, EventOut,ActivityLogCreate,
    DemoOut,EventCreate,MessageMasterCreate, MessageMasterUpdate, MessageMasterOut,
    DripSequenceCreate,UnifiedActivityOut, DripSequenceOut, DripSequenceListOut,
    LeadCreate, LeadUpdateWeb, UserUpdate, MeetingScheduleWeb,
    PostMeetingWeb, DemoScheduleWeb,MarkActivityDonePayload, PostDemoWeb,ReminderOut,
    EventReschedulePayload, EventReassignPayload, EventCancelPayload,
    EventNotesUpdatePayload, ActivityLogUpdate, MasterDataCreate, MasterDataOut,
    ClientOut, ConvertLeadToClientPayload, ClientUpdate, LeadAttachmentOut,
    # --- START: NEW IMPORTS ---
    ConvertToProposalPayload, ProposalSentOut
    # --- END: NEW IMPORTS ---
)
from app.crud import (
    create_user, verify_user, get_user_by_username, change_user_password,
    get_users,create_reminder, get_all_leads_with_last_activity,create_activity_log , update_lead_status, get_scheduled_demos,get_scheduled_meetings, get_all_meetings, get_all_demos, get_scheduled_meetings,
    create_activity_log, get_all_unified_activities, get_tasks_by_username,
    get_activities_by_lead_id, get_lead_history, get_all_leads, get_lead_by_id,
    update_lead, save_lead, get_user_by_id, update_user, delete_user,
    get_pending_reminders, create_event, complete_meeting, complete_demo,
    is_user_available, get_user_by_name, create_message, complete_scheduled_activity,
    get_all_messages, get_message_by_id, update_message, delete_message,
    create_drip_sequence, get_all_drip_sequences, get_drip_sequence_by_id,
    update_drip_sequence, delete_drip_sequence, assign_drip_to_lead, log_sent_drip_message,
    reschedule_meeting, reassign_meeting, cancel_meeting, update_meeting_notes,
    reschedule_demo, reassign_demo, cancel_demo, update_demo_notes,
    update_activity_log, get_master_data_by_category, create_master_data, delete_master_data, delete_activity_log, delete_reminder,
    create_client, get_all_clients, get_client_by_id, convert_lead_to_client, update_client,
    get_user_by_phone,
    soft_delete_lead, get_deleted_leads, restore_lead, add_lead_attachment, delete_lead_attachment,
    # --- START: NEW IMPORTS ---
    convert_lead_to_proposal, get_all_proposals
    # --- END: NEW IMPORTS ---
)
from sqlalchemy.orm import Session,joinedload
from app.db import get_db, get_db_session_for_company, COMPANY_TO_ENV_MAP
from app.gpt_parser import parse_report_request, parse_intent_and_fields
from app.crud import generate_user_performance_data
from app.report_generator import create_performance_report_pdf
from app.handlers.message_router import route_message
from app.gpt_parser import parse_datetime_from_text
from datetime import datetime, timedelta, date
from app.message_sender import send_whatsapp_message, send_whatsapp_message_with_media
from app.crud import assign_drip_to_lead, log_sent_drip_message
import asyncio
from app.reminders import reminder_loop, drip_campaign_loop
from app.scheduler import scheduler
from app.config import UPLOAD_DIRECTORY


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = FastAPI()

origins = [
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Application startup: Launching background tasks...")
    asyncio.create_task(reminder_loop())
    asyncio.create_task(drip_campaign_loop())
    logger.info("✅ Background loops for reminders and drips have been started.")
    
    try:
        scheduler.start()
        logger.info("✅ Background scheduler for weekly reports has been started.")
    except Exception as e:
        logger.error(f"❌ Failed to start the scheduler: {e}", exc_info=True)


main_router = APIRouter()
web_router = APIRouter()

if not os.path.exists(UPLOAD_DIRECTORY):
    os.makedirs(UPLOAD_DIRECTORY)


COUNTRY_PHONE_CODES = {
    "india": "+91",
    "united states": "+1",
    "usa": "+1",
    "united arab emirates": "+971",
    "uae": "+971",
    "united kingdom": "+44",
    "uk": "+44",
    "saudi arabia": "+966",
    "qatar": "+974",
    "oman": "+968",
    "bahrain": "+973",
    "kuwait": "+965",
    "australia": "+61",
    "canada": "+1",
}


LOCAL_TIMEZONE = pytz.timezone('Asia/Kolkata')

def get_country_phone_code(country_name: str) -> Optional[str]:
    if not country_name:
        return None
    return COUNTRY_PHONE_CODES.get(country_name.lower().strip())


@main_router.post("/register", response_model=UserResponse, tags=["Authentication"])
def register_user(user: UserCreate):
    # Manually get a DB session for the specified company
    db = get_db_session_for_company(user.company_name)
    try:
        existing = get_user_by_username(db, user.username)
        if existing:
            raise HTTPException(status_code=400, detail="Username already exists in this company")
        
        new_user = create_user(db, user)
        return new_user
    finally:
        db.close()


@main_router.post("/login", response_model=UserResponse, tags=["Authentication"])
def login_user(user: UserLogin):
    # Manually get a DB session for the specified company
    db = get_db_session_for_company(user.company_name)
    try:
        authenticated_user = verify_user(db, user.username, user.password)
        if not authenticated_user:
            raise HTTPException(status_code=401, detail="Invalid username or password for the specified company")
        return authenticated_user
    finally:
        db.close()

@main_router.post("/change-password", tags=["Users"])
def change_password(password_data: UserPasswordChange, db: Session = Depends(get_db)):
    # Uses the get_db dependency, which requires X-Company-Name header
    updated_user = change_user_password(db, password_data)
    if not updated_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or old password")
    db.commit()
    return {"status": "success", "message": "Password updated successfully"}

@main_router.get("/users", response_model=list[UserResponse], tags=["Users"])
def get_all_users(db: Session = Depends(get_db)):
    # Uses the get_db dependency
    db_users = get_users(db)
    response = []
    for user in db_users:
        response.append(UserResponse.model_validate(user))
    return response

@web_router.put("/users/{user_id}", response_model=UserResponse)
def update_user_details(user_id: int, user_data: UserUpdate, db: Session = Depends(get_db)):
    # Uses the get_db dependency
    updated_user = update_user(db, user_id, user_data)
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
    db.commit()
    db.refresh(updated_user)
    return updated_user

@web_router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_user(user_id: int, db: Session = Depends(get_db)):
    # Uses the get_db dependency
    success = delete_user(db, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="User not found")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@web_router.get("/master-data/{category}", response_model=List[MasterDataOut], tags=["Masters"])
def api_get_master_data(category: str, db: Session = Depends(get_db)):
    # Uses the get_db dependency
    return get_master_data_by_category(db, category=category)

@web_router.post("/master-data", response_model=MasterDataOut, tags=["Masters"])
def api_create_master_data(item: MasterDataCreate, db: Session = Depends(get_db)):
    # Uses the get_db dependency
    return create_master_data(db, item=item)

@web_router.delete("/master-data/{item_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Masters"])
def api_delete_master_data(item_id: int, db: Session = Depends(get_db)):
    # Uses the get_db dependency
    success = delete_master_data(db, item_id=item_id)
    if not success:
        raise HTTPException(status_code=404, detail="Master data item not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def handle_generate_report(msg_text: str, sender_phone: str):
    pdf_file_path = None
    db_session = None
    try:
        username, company_name, start_date, end_date = parse_report_request(msg_text)

        if not all([username, company_name, start_date, end_date]):
            error_msg = ("⚠️ Invalid format. Please use:\n\n"
                         "`Generate report of [username] for [company name] from [dd/mm/yy] to [dd/mm/yy]`")
            send_whatsapp_message(number=sender_phone, message=error_msg)
            return

        try:
            db_session = get_db_session_for_company(company_name)
        except HTTPException as e:
            logger.warning(f"Report generation failed for company '{company_name}': {e.detail}")
            send_whatsapp_message(number=sender_phone, message=f"❌ {e.detail}")
            return

        user = get_user_by_name(db_session, username)
        if not user:
            error_msg = f"❌ User '{username}' not found in company '{company_name}'. Please check the name."
            send_whatsapp_message(number=sender_phone, message=error_msg)
            return
            
        send_whatsapp_message(number=sender_phone, message=f"⏳ Generating report for *{user.username}* from company *{company_name}*... Please wait.")

        report_data = generate_user_performance_data(db_session, user.id, start_date, end_date)
        if not report_data:
            error_msg = "❌ Could not generate report data. An internal error occurred."
            send_whatsapp_message(number=sender_phone, message=error_msg)
            return

        pdf_file_path = create_performance_report_pdf(report_data, user.username, start_date, end_date, UPLOAD_DIRECTORY)
        
        message_text = f"📊 Here is the performance report for *{user.username}* from {start_date.strftime('%d/%m/%y')} to {end_date.strftime('%d/%m/%y')}."
        success = send_whatsapp_message_with_media(
            number=sender_phone,
            file_path=pdf_file_path,
            caption=message_text,
            message_type='document'
        )

        if not success:
            send_whatsapp_message(number=sender_phone, message="❌ Failed to send the PDF report.")

    except Exception as e:
        logger.error(f"❌ Critical error in handle_generate_report: {e}", exc_info=True)
        send_whatsapp_message(number=sender_phone, message="❌ An unexpected error occurred while generating your report.")
    
    finally:
        if db_session:
            db_session.close()
        if pdf_file_path:
            logger.info("Waiting for 15 seconds before deleting the temporary report file to allow for download...")
            await asyncio.sleep(15)
        if pdf_file_path and os.path.exists(pdf_file_path):
            os.remove(pdf_file_path)
            logger.info(f"Cleaned up temporary report file: {pdf_file_path}")
            
@main_router.get("/leads/{user_id}", response_model=list[LeadResponse], tags=["Leads & History"])
async def get_leads_by_user_id(user_id: str, db: Session = Depends(get_db)):
    leads = db.query(Lead).filter(Lead.assigned_to == user_id, Lead.isActive == True).all()
    if not leads:
        raise HTTPException(status_code=404, detail="No leads found for this user")
    return leads

@main_router.get("/tasks/{username}", response_model=list[TaskOut], tags=["Leads & History"])
def get_user_tasks(username: str, db: Session = Depends(get_db)):
    results = get_tasks_by_username(db, username)
    if not results:
        return []
    tasks_out = [ TaskOut(id=row.id, lead_id=row.lead_id, company_name=row.company_name or "Deleted Lead", event_type=row.event_type, event_time=row.event_time, remark=row.remark) for row in results ]
    return tasks_out

@main_router.get("/activities/{lead_id}", response_model=list[ActivityLogOut], tags=["Leads & History"])
def get_lead_activities(lead_id: int, db: Session = Depends(get_db)):
    activities = get_activities_by_lead_id(db, lead_id)
    if not activities:
        raise HTTPException(status_code=404, detail="No activities found for this lead")
    return activities

@main_router.get("/history/{lead_id}", response_model=list[HistoryItemOut], tags=["Leads & History"])
def get_lead_history_route(lead_id: int, db: Session = Depends(get_db)):
    history = get_lead_history(db, lead_id)
    if not history:
        raise HTTPException(status_code=404, detail="No history found for this lead. The lead may not exist.")
    return history

@main_router.get("/webhook", tags=["WhatsApp & App Integration"])
async def webhook_verification(request: Request):
    logger.info("GET request received at /webhook for verification.")
    return Response(content="Webhook Verified", status_code=200)

@main_router.post("/webhook", tags=["WhatsApp & App Integration"])
async def receive_message(req: Request):
    try:
        data = await req.json()
    except Exception as e:
        logger.error(f"❌ Failed to parse incoming JSON: {e}")
        return Response(status_code=status.HTTP_400_BAD_REQUEST, content="Invalid JSON")

    logger.info(f"📦 Incoming Payload: {data}")

    top_level_type = data.get("type")
    inner_data_payload = data.get("data", {})

    if top_level_type == "incoming":
        message_metadata = inner_data_payload.get("metadata", {}).get("message", {})
        message_content_type = message_metadata.get("type")
        
        message_text = message_metadata.get("text") or message_metadata.get("caption", "")
        message_text = message_text.strip()
        
        if (message_content_type == "text" or message_content_type == "media") and message_text:
            sender_phone = inner_data_payload.get("phone") or inner_data_payload.get("metadata", {}).get("other_party", {}).get("number")

            source = data.get("event", "whatsapp")
            reply_url = ""

            if not all([sender_phone, message_text]):
                logger.warning(f"Missing critical fields. Sender: {sender_phone}, Message: '{message_text}'.")
                return Response(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content="Missing fields")
            
            intent, _ = parse_intent_and_fields(message_text)
            
            if intent == "generate_report":
                await handle_generate_report(message_text, sender_phone)
                return Response(status_code=status.HTTP_200_OK)
            
            else:
                db_session = None
                found_company = None
                for company_name in COMPANY_TO_ENV_MAP.keys():
                    db_temp = None
                    try:
                        db_temp = get_db_session_for_company(company_name)
                        if get_user_by_phone(db_temp, sender_phone):
                            db_session = db_temp
                            found_company = company_name
                            logger.info(f"✅ User {sender_phone} found in company: {found_company}")
                            break
                    except HTTPException as e:
                        logger.error(f"Could not check db for company '{company_name}': {e.detail}")
                        if db_temp: db_temp.close()
                        continue
                    finally:
                        if not db_session and db_temp:
                            db_temp.close()

                if not db_session:
                    logger.warning(f"User with phone {sender_phone} not found in any configured company.")
                    return Response(status_code=status.HTTP_404_NOT_FOUND, content="User not found")
                
                try:
                    logger.info(f"Routing message from {sender_phone} to handler for company '{found_company}'.")
                    response_from_handler = await route_message(sender_phone, message_text, reply_url, source, db_session)
                    return response_from_handler
                finally:
                    if db_session:
                        db_session.close()

        elif message_content_type == "reaction":
            logger.info("Skipping reaction message.")
            return Response(status_code=status.HTTP_200_OK)
        else:
            logger.info(f"Skipping non-processable message type: {message_content_type}")
            return Response(status_code=status.HTTP_200_OK)
    else:
        logger.info(f"Skipping non-relevant webhook payload: type='{top_level_type}'")
        return Response(status_code=status.HTTP_200_OK)


@main_router.post("/app", tags=["WhatsApp & App Integration"])
async def receive_app_message(req: Request):
    try:
        data = await req.json()
    except Exception:
        return {"status": "error", "reply": "Invalid JSON"}
    logger.info(f"📱 Incoming App Payload: {data}")
    sender_phone = data.get("user_phone") or data.get("phone")
    message_text = data.get("message", "").strip()
    if not all([sender_phone, message_text]):
        return {"status": "error", "reply": f"Missing fields: user_phone and/or message"}

    db_session = None
    found_company = None
    for company_name in COMPANY_TO_ENV_MAP.keys():
        db_temp = None
        try:
            db_temp = get_db_session_for_company(company_name)
            if get_user_by_phone(db_temp, sender_phone):
                db_session = db_temp
                found_company = company_name
                break
        finally:
            if not db_session and db_temp:
                db_temp.close()

    if not db_session:
        return {"status": "error", "reply": "User not found in any company."}

    try:
        response_from_handler = await route_message(sender_phone, message_text, "", "app", db_session)
        return response_from_handler
    finally:
        if db_session:
            db_session.close()


@web_router.post("/leads", response_model=LeadResponse)
def create_lead_from_web(lead_data: LeadCreate, db: Session = Depends(get_db)):
    try:
        created_lead = save_lead(db, lead_data)
        
        assignee = get_user_by_name(db, lead_data.assigned_to)
        if assignee and assignee.usernumber:
            creator_name = lead_data.created_by
            contact_name = created_lead.contacts[0].contact_name if created_lead.contacts else "N/A"
            contact_phone= created_lead.contacts[0].phone if created_lead.contacts else "N/A"
            
            message = (f"📢 *New Lead Assigned to You*\n\n"
                       f"🏢 *Company:* {created_lead.company_name}\n"
                       f"👤 *Contact:* {contact_name}\n"
                       f"📱 *Phone:* {contact_phone}\n"
                       f"Assigned By: {creator_name}")
            
            send_whatsapp_message(number=assignee.usernumber, message=message)
            logger.info(f"Sent new lead notification to {assignee.username} at {assignee.usernumber}")

        return created_lead
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")

# --- START: NEW PROPOSAL ENDPOINTS ---
@web_router.post("/leads/{lead_id}/convert-to-proposal", response_model=ProposalSentOut, tags=["Leads", "Proposals"])
def convert_lead_to_proposal_endpoint(
    lead_id: int,
    payload: ConvertToProposalPayload,
    db: Session = Depends(get_db)
):
    try:
        converted_by = "Web User" # Replace with actual authenticated user if available
        new_proposal = convert_lead_to_proposal(db, lead_id, payload, converted_by)
        return new_proposal
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error converting lead {lead_id} to proposal: {e}")
        raise HTTPException(status_code=500, detail="Failed to convert lead to proposal.")

@web_router.get("/proposals", response_model=List[ProposalSentOut], tags=["Proposals"])
def get_all_proposals_endpoint(db: Session = Depends(get_db)):
    proposals = get_all_proposals(db)
    return proposals
# --- END: NEW PROPOSAL ENDPOINTS ---

# --- START: FIX - ADDED GET /web/leads ENDPOINT ---
@web_router.get("/leads", response_model=list[LeadResponse], tags=["Leads"])
def get_all_leads_web(db: Session = Depends(get_db)):
    """
    Fetches all active leads with their last activity, intended for web UI consumption.
    """
    leads = get_all_leads_with_last_activity(db)
    if not leads:
        return []
    return leads
# --- END: FIX ---

@web_router.get("/leads/deleted", response_model=list[LeadResponse], tags=["Leads"])
def get_all_deleted_leads(db: Session = Depends(get_db)):
    deleted_leads = get_deleted_leads(db)
    return [LeadResponse.model_validate(lead) for lead in deleted_leads]

@web_router.get("/leads/{lead_id}", response_model=LeadResponse)
def get_single_lead_for_web(lead_id: int, db: Session = Depends(get_db)):
    lead = get_lead_by_id(db, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead

@web_router.delete("/leads/{lead_id}", response_model=LeadResponse, tags=["Leads"])
def api_soft_delete_lead(lead_id: int, db: Session = Depends(get_db)):
    deleted_lead = soft_delete_lead(db, lead_id)
    if not deleted_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return deleted_lead

@web_router.put("/leads/{lead_id}/restore", response_model=LeadResponse, tags=["Leads"])
def api_restore_lead(lead_id: int, db: Session = Depends(get_db)):
    restored_lead = restore_lead(db, lead_id)
    if not restored_lead:
        raise HTTPException(status_code=404, detail="Lead not found or could not be restored.")
    return restored_lead

@web_router.post("/leads/{lead_id}/convert-to-client", response_model=ClientOut, tags=["Leads", "Clients"])
def convert_lead_to_client_endpoint(
    lead_id: int,
    conversion_data: ConvertLeadToClientPayload,
    db: Session = Depends(get_db)
):
    try:
        converted_by_user = "Web User"
        client = convert_lead_to_client(db, lead_id, conversion_data, converted_by_user)
        return client
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error converting lead {lead_id} to client: {e}")
        raise HTTPException(status_code=500, detail="Failed to convert lead to client. Internal server error.")

@web_router.post("/leads/{lead_id}/attachments", response_model=LeadAttachmentOut, tags=["Leads", "Attachments"])
def upload_lead_attachment(
    lead_id: int,
    uploaded_by: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    lead = get_lead_by_id(db, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    unique_id = uuid.uuid4().hex
    file_extension = os.path.splitext(file.filename)[1]
    attachment_filename = f"lead_{lead_id}_{unique_id}{file_extension}"
    file_path = os.path.join(UPLOAD_DIRECTORY, attachment_filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    attachment_data = schemas.LeadAttachmentCreate(
        file_path=attachment_filename,
        original_file_name=file.filename,
        uploaded_by=uploaded_by
    )
    return add_lead_attachment(db, lead_id, attachment_data)

@web_router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Attachments"])
def api_delete_lead_attachment(attachment_id: int, db: Session = Depends(get_db)):
    attachment = db.query(LeadAttachment).filter(LeadAttachment.id == attachment_id).first()
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    file_path = os.path.join(UPLOAD_DIRECTORY, attachment.file_path)
    
    success = delete_lead_attachment(db, attachment_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete attachment from database.")

    if os.path.exists(file_path):
        os.remove(file_path)

    return Response(status_code=status.HTTP_204_NO_CONTENT)

@web_router.get("/clients", response_model=List[ClientOut], tags=["Clients"])
def get_all_clients_route(db: Session = Depends(get_db)):
    clients = get_all_clients(db)
    return [ClientOut.model_validate(c) for c in clients]

@web_router.get("/clients/{client_id}", response_model=ClientOut, tags=["Clients"])
def get_client_by_id_route(client_id: int, db: Session = Depends(get_db)):
    client = get_client_by_id(db, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return ClientOut.model_validate(client)

@web_router.put("/clients/{client_id}", response_model=ClientOut, tags=["Clients"])
def update_client_route(client_id: int, client_data: ClientUpdate, db: Session = Depends(get_db)):
    updated_client = update_client(db, client_id, client_data)
    if not updated_client:
        raise HTTPException(status_code=404, detail="Client not found")
    db.commit()
    db.refresh(updated_client)
    return ClientOut.model_validate(updated_client)


@web_router.get("/meetings", response_model=list[EventOut])
def get_all_scheduled_meetings(db: Session = Depends(get_db)):
    meetings = get_scheduled_meetings(db)
    for m in meetings:
        if m.event_time and m.event_time.tzinfo is None:
            m.event_time = pytz.utc.localize(m.event_time)
        if m.event_end_time and m.event_end_time.tzinfo is None:
            m.event_end_time = pytz.utc.localize(m.event_end_time)
    return [EventOut.model_validate(m) for m in meetings]

@web_router.get("/meetings/all", response_model=list[EventOut])
def get_every_meeting(db: Session = Depends(get_db)):
    meetings_from_db = get_all_meetings(db)
    response = []
    for meeting in meetings_from_db:
        aware_event_time = pytz.utc.localize(meeting.event_time) if meeting.event_time and meeting.event_time.tzinfo is None else meeting.event_time
        aware_end_time = pytz.utc.localize(meeting.event_end_time) if meeting.event_end_time and meeting.event_end_time.tzinfo is None else meeting.event_end_time
        response.append(
            EventOut(
                id=meeting.id, lead_id=meeting.lead_id, assigned_to=meeting.assigned_to,
                event_type=meeting.event_type, meeting_type=meeting.meeting_type,
                event_time=aware_event_time, 
                event_end_time=aware_end_time,
                created_by=meeting.created_by, remark=meeting.remark,
                phase=meeting.phase, created_at=meeting.created_at
            )
        )
    return response

@web_router.get("/demos", response_model=list[DemoOut])
def get_all_scheduled_demos(db: Session = Depends(get_db)):
    demos = get_scheduled_demos(db)
    for d in demos:
        if d.start_time and d.start_time.tzinfo is None:
            d.start_time = pytz.utc.localize(d.start_time)
        if d.event_end_time and d.event_end_time.tzinfo is None:
            d.event_end_time = pytz.utc.localize(d.event_end_time)
    return [DemoOut.model_validate(d) for d in demos]

@web_router.get("/demos/all", response_model=list[DemoOut])
def get_every_demo(db: Session = Depends(get_db)):
    demos_from_db = get_all_demos(db)
    response = []
    for demo in demos_from_db:
        aware_start_time = pytz.utc.localize(demo.start_time) if demo.start_time and demo.start_time.tzinfo is None else demo.start_time
        aware_end_time = pytz.utc.localize(demo.event_end_time) if demo.event_end_time and demo.event_end_time.tzinfo is None else demo.event_end_time
        response.append(
            DemoOut(
                id=demo.id, lead_id=demo.lead_id, scheduled_by=demo.scheduled_by,
                assigned_to=demo.assigned_to, 
                start_time=aware_start_time,
                event_end_time=aware_end_time, 
                phase=demo.phase,
                remark=demo.remark, created_at=demo.created_at, updated_at=demo.updated_at
            )
        )
    return response

@web_router.post("/meetings/schedule", response_model=EventOut)
def schedule_meeting_from_web(meeting_data: MeetingScheduleWeb, db: Session = Depends(get_db)):
    assignee = get_user_by_id(db, meeting_data.assigned_to_user_id)
    creator = get_user_by_id(db, meeting_data.created_by_user_id)
    if not assignee or not creator:
        raise HTTPException(status_code=404, detail="Assignee or Creator user not found")

    if not meeting_data.lead_id and not meeting_data.proposal_id:
        raise HTTPException(status_code=400, detail="Either lead_id or proposal_id must be provided.")

    start_time_req = meeting_data.start_time
    end_time_req = meeting_data.end_time

    if start_time_req.tzinfo is None:
        start_time_utc_aware = LOCAL_TIMEZONE.localize(start_time_req).astimezone(pytz.utc)
    else:
        start_time_utc_aware = start_time_req.astimezone(pytz.utc)

    if end_time_req.tzinfo is None:
        end_time_utc_aware = LOCAL_TIMEZONE.localize(end_time_req).astimezone(pytz.utc)
    else:
        end_time_utc_aware = end_time_req.astimezone(pytz.utc)

    start_time_local_aware = start_time_utc_aware.astimezone(LOCAL_TIMEZONE)
    start_time_utc_naive = start_time_utc_aware.replace(tzinfo=None)
    end_time_utc_naive = end_time_utc_aware.replace(tzinfo=None)

    conflicting_event = is_user_available(db, assignee.username, assignee.usernumber, start_time_utc_naive, end_time_utc_naive)

    if conflicting_event:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"User '{assignee.username}' is already booked at this time.")

    event_schema = EventCreate(
        lead_id=meeting_data.lead_id,
        proposal_id=meeting_data.proposal_id,
        assigned_to=assignee.username, 
        event_type="Meeting",
        meeting_type=meeting_data.meeting_type, 
        event_time=start_time_utc_naive,
        event_end_time=end_time_utc_naive,
        created_by=creator.username, 
        remark="Scheduled via Web UI"
    )
    
    if meeting_data.lead_id:
        update_lead_status(db, lead_id=meeting_data.lead_id, status="Meeting Scheduled", updated_by=creator.username)
        parent = get_lead_by_id(db, meeting_data.lead_id)
    else: # It's a proposal
        parent = db.query(ProposalSent).filter(ProposalSent.id == meeting_data.proposal_id).first()

    new_event = create_event(db, event_schema)
    
    if parent and assignee.usernumber:
        time_formatted = start_time_local_aware.strftime('%A, %b %d at %I:%M %p')
        contact_name = parent.contacts[0].contact_name if parent.contacts else "N/A"
        message = (f"📢 *New Meeting Scheduled for You*\n\n🏢 *Company:* {parent.company_name}\n👤 *Contact:* {contact_name}\n🕒 *Time:* {time_formatted}\nScheduled By: {creator.username}")
        send_whatsapp_message(number=assignee.usernumber, message=message)
        logger.info(f"Sent new meeting notification to {assignee.username} at {assignee.usernumber}")

    time_formatted_reminder = start_time_local_aware.strftime('%A, %b %d at %I:%M %p')
    reminder_message = f"You have a meeting scheduled for *{parent.company_name}* on {time_formatted_reminder}."
    one_day_before = new_event.event_time - timedelta(days=1)
    if one_day_before > datetime.utcnow():
        create_reminder(db, ReminderCreate(lead_id=new_event.lead_id, proposal_id=new_event.proposal_id, user_id=assignee.id, assigned_to=assignee.username, remind_time=one_day_before, message=f"(1 day away) {reminder_message}", is_hidden_from_activity_log=True))
    one_hour_before = new_event.event_time - timedelta(hours=1)
    if one_hour_before > datetime.utcnow():
        create_reminder(db, ReminderCreate(lead_id=new_event.lead_id, proposal_id=new_event.proposal_id, user_id=assignee.id, assigned_to=assignee.username, remind_time=one_hour_before, message=f"(in 1 hour) {reminder_message}", is_hidden_from_activity_log=True))
    
    if new_event.event_time and new_event.event_time.tzinfo is None:
        new_event.event_time = pytz.utc.localize(new_event.event_time)
    if new_event.event_end_time and new_event.event_end_time.tzinfo is None:
        new_event.event_end_time = pytz.utc.localize(new_event.event_end_time)
    
    return new_event


@web_router.post("/meetings/complete", response_model=schemas.StatusMessage)
def post_meeting_from_web(data: PostMeetingWeb, db: Session = Depends(get_db)):
    event = complete_meeting(db=db, meeting_id=data.meeting_id, notes=data.notes, updated_by=data.updated_by)
    if not event:
        raise HTTPException(status_code=404, detail=f"Meeting with ID {data.meeting_id} not found or already completed.")
    return {"status": "success", "message": f"Meeting {data.meeting_id} has been marked as complete."}

@web_router.post("/demos/schedule", response_model=DemoOut)
def schedule_demo_from_web(demo_data: DemoScheduleWeb, db: Session = Depends(get_db)):
    assignee = get_user_by_id(db, demo_data.assigned_to_user_id)
    creator = get_user_by_id(db, demo_data.created_by_user_id)
    
    if not demo_data.lead_id and not demo_data.proposal_id:
        raise HTTPException(status_code=400, detail="Either lead_id or proposal_id must be provided.")
    
    if demo_data.lead_id:
        parent = get_lead_by_id(db, demo_data.lead_id)
    else:
        parent = db.query(ProposalSent).filter(ProposalSent.id == demo_data.proposal_id).first()

    if not all([assignee, creator, parent]):
        raise HTTPException(status_code=404, detail="Assignee, Creator, or Parent entity (Lead/Proposal) not found")

    start_time_req = demo_data.start_time
    end_time_req = demo_data.end_time

    if start_time_req.tzinfo is None: start_time_utc_aware = LOCAL_TIMEZONE.localize(start_time_req).astimezone(pytz.utc)
    else: start_time_utc_aware = start_time_req.astimezone(pytz.utc)

    if end_time_req.tzinfo is None: end_time_utc_aware = LOCAL_TIMEZONE.localize(end_time_req).astimezone(pytz.utc)
    else: end_time_utc_aware = end_time_req.astimezone(pytz.utc)

    start_time_local_aware = start_time_utc_aware.astimezone(LOCAL_TIMEZONE)
    start_time_utc_naive = start_time_utc_aware.replace(tzinfo=None)
    end_time_utc_naive = end_time_utc_aware.replace(tzinfo=None)

    conflicting_event = is_user_available(db, assignee.username, assignee.usernumber, start_time_utc_naive, end_time_utc_naive)
    if conflicting_event:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"User '{assignee.username}' is already booked at this time.")
    
    new_demo = Demo(
        lead_id=demo_data.lead_id,
        proposal_id=demo_data.proposal_id,
        assigned_to=assignee.usernumber, 
        scheduled_by=creator.username, 
        start_time=start_time_utc_naive, 
        event_end_time=end_time_utc_naive
    )
    
    db.add(new_demo)
    db.commit()
    db.refresh(new_demo)
    
    if demo_data.lead_id:
        update_lead_status(db, lead_id=demo_data.lead_id, status="Demo Scheduled", updated_by=creator.username)

    if assignee.usernumber:
        time_formatted = start_time_local_aware.strftime('%A, %b %d at %I:%M %p')
        contact_name = parent.contacts[0].contact_name if parent.contacts else "N/A"
        message = (f"📢 *New Demo Scheduled for You*\n\n🏢 *Company:* {parent.company_name}\n👤 *Contact:* {contact_name}\n🕒 *Time:* {time_formatted}\nScheduled By: {creator.username}")
        send_whatsapp_message(number=assignee.usernumber, message=message)
        logger.info(f"Sent new demo notification to {assignee.username} at {assignee.usernumber}")

    time_formatted_reminder = start_time_local_aware.strftime('%A, %b %d at %I:%M %p')
    reminder_message = f"You have a demo scheduled for *{parent.company_name}* on {time_formatted_reminder}."
    one_day_before = new_demo.start_time - timedelta(days=1)
    if one_day_before > datetime.utcnow():
        create_reminder(db, ReminderCreate(lead_id=new_demo.lead_id, proposal_id=new_demo.proposal_id, user_id=assignee.id, assigned_to=assignee.username, remind_time=one_day_before, message=f"(1 day away) {reminder_message}", is_hidden_from_activity_log=True))
    one_hour_before = new_demo.start_time - timedelta(hours=1)
    if one_hour_before > datetime.utcnow():
        create_reminder(db, ReminderCreate(lead_id=new_demo.lead_id, proposal_id=new_demo.proposal_id, user_id=assignee.id, assigned_to=assignee.username, remind_time=one_hour_before, message=f"(in 1 hour) {reminder_message}", is_hidden_from_activity_log=True))
    
    if new_demo.start_time and new_demo.start_time.tzinfo is None:
        new_demo.start_time = pytz.utc.localize(new_demo.start_time)
    if new_demo.event_end_time and new_demo.event_end_time.tzinfo is None:
        new_demo.event_end_time = pytz.utc.localize(new_demo.event_end_time)

    return new_demo


@web_router.post("/demos/complete", response_model=schemas.StatusMessage)
def post_demo_from_web(data: PostDemoWeb, db: Session = Depends(get_db)):
    demo = complete_demo(db, data.demo_id, data.notes, data.updated_by)
    if not demo:
        raise HTTPException(status_code=404, detail="Demo not found or already completed.")
    return {"status": "success", "message": f"Demo {data.demo_id} marked as complete."}

@web_router.put("/leads/{lead_id}", response_model=LeadResponse)
def update_lead_from_web(lead_id: int, lead_data: LeadUpdateWeb, db: Session = Depends(get_db)):
    db_lead = update_lead(db, lead_id, lead_data)
    if not db_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return db_lead

@web_router.post("/messages", response_model=MessageMasterOut)
def api_create_message_with_file(
    message_name: str = Form(...),
    message_content: Optional[str] = Form(None),
    message_type: str = Form(...),
    created_by: str = Form(...),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    attachment_filename = None
    if file:
        unique_id = uuid.uuid4().hex
        file_extension = os.path.splitext(file.filename)[1]
        attachment_filename = f"{unique_id}{file_extension}"
        file_path = os.path.join(UPLOAD_DIRECTORY, attachment_filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

    message_data = MessageMasterCreate(
        message_name=message_name,
        message_content=message_content,
        message_type=message_type,
        created_by=created_by,
        attachment_path=attachment_filename
    )
    return create_message(db, message_data)

@web_router.get("/messages", response_model=list[MessageMasterOut])
def api_get_all_messages(db: Session = Depends(get_db)):
    return get_all_messages(db)

@web_router.put("/messages/{message_id}", response_model=MessageMasterOut)
def api_update_message_with_file(
    message_id: int,
    message_name: str = Form(...),
    message_content: Optional[str] = Form(None),
    message_type: str = Form(...),
    existing_attachment_path: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    attachment_filename = existing_attachment_path
    if file:
        unique_id = uuid.uuid4().hex
        file_extension = os.path.splitext(file.filename)[1]
        attachment_filename = f"{unique_id}{file_extension}"
        file_path = os.path.join(UPLOAD_DIRECTORY, attachment_filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    
    elif not existing_attachment_path:
        attachment_filename = None

    message_data = MessageMasterUpdate(
        message_name=message_name,
        message_content=message_content,
        message_type=message_type,
        attachment_path=attachment_filename
    )

    updated_message = update_message(db, message_id, message_data)
    if not updated_message:
        raise HTTPException(status_code=404, detail="Message not found")
    return updated_message

@web_router.delete("/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
def api_delete_message(message_id: int, db: Session = Depends(get_db)):
    if not delete_message(db, message_id):
        raise HTTPException(status_code=404, detail="Message not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@web_router.post("/drip-sequences", response_model=DripSequenceOut)
def api_create_drip_sequence(drip_data: DripSequenceCreate, db: Session = Depends(get_db)):
    return create_drip_sequence(db, drip_data)

@web_router.get("/drip-sequences", response_model=list[DripSequenceListOut])
def api_get_all_drip_sequences(db: Session = Depends(get_db)):
    return get_all_drip_sequences(db)

@web_router.get("/drip-sequences/{drip_id}", response_model=DripSequenceOut)
def api_get_drip_sequence(drip_id: int, db: Session = Depends(get_db)):
    drip = get_drip_sequence_by_id(db, drip_id)
    if not drip:
        raise HTTPException(status_code=404, detail="Drip sequence not found")
    return drip

@web_router.put("/drip-sequences/{drip_id}", response_model=DripSequenceOut)
def api_update_drip_sequence(drip_id: int, drip_data: DripSequenceCreate, db: Session = Depends(get_db)):
    updated_drip = update_drip_sequence(db, drip_id, drip_data)
    if not updated_drip:
        raise HTTPException(status_code=404, detail="Drip sequence not found")
    return updated_drip

@web_router.delete("/drip-sequences/{drip_id}", status_code=status.HTTP_204_NO_CONTENT)
def api_delete_drip_sequence(drip_id: int, db: Session = Depends(get_db)):
    if not delete_drip_sequence(db, drip_id):
        raise HTTPException(status_code=404, detail="Drip sequence not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@web_router.get("/activities/pending", response_model=list[ReminderOut])
def get_pending_activities(db: Session = Depends(get_db)):
    reminders = get_pending_reminders(db)
    for rem in reminders:
        if rem.remind_time and rem.remind_time.tzinfo is None:
            rem.remind_time = pytz.utc.localize(rem.remind_time)
        if rem.created_at and rem.created_at.tzinfo is None:
            rem.created_at = pytz.utc.localize(rem.created_at)
    return [ReminderOut.model_validate(rem) for rem in reminders]

@web_router.post("/leads/{lead_id}/activity", response_model=ActivityLogOut)
def create_activity_with_attachment(
    lead_id: int,
    details: str = Form(...),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    lead = get_lead_by_id(db, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    attachment_filename = None
    if file:
        unique_id = uuid.uuid4().hex
        file_extension = os.path.splitext(file.filename)[1]
        attachment_filename = f"{unique_id}{file_extension}"

        file_path = os.path.join(UPLOAD_DIRECTORY, attachment_filename)

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

    activity_data = ActivityLogCreate(
        lead_id=lead.id,
        phase=lead.status,
        details=details
    )

    db_activity = models.ActivityLog(
        **activity_data.model_dump(),
        attachment_path=attachment_filename
    )
    db.add(db_activity)
    db.commit()
    db.refresh(db_activity)

    return db_activity

@web_router.post("/leads/upload-bulk")
def upload_leads_from_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    success_count = 0
    errors = []

    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload an Excel file.")

    try:
        df = pd.read_excel(file.file, dtype=str).fillna('')

        column_map = {col.strip().lower(): col for col in df.columns}

        def get_value(row, cleaned_name):
            original_name = column_map.get(cleaned_name)
            if original_name and row[original_name] and str(row[original_name]).strip():
                return str(row[original_name]).strip()
            return None

        for index, row in df.iterrows():
            try:
                assignee_name = get_value(row, 'assigned_to')
                if not assignee_name:
                    raise ValueError("The required field 'assigned_to' is missing or empty.")

                assignee_user = get_user_by_name(db, assignee_name)
                if not assignee_user:
                    raise ValueError(f"Assigned user '{assignee_name}' not found in the database.")

                contacts_for_lead = []
                contact_name = get_value(row, 'contact_name')
                phone_number = get_value(row, 'phone')

                if contact_name or phone_number:
                    country_name = get_value(row, 'country')
                    final_phone_number = phone_number

                    if phone_number and country_name:
                        try:
                            sanitized_phone = re.sub(r'[\s\-\(\)]', '', phone_number)
                            country_info = CountryInfo(country_name)
                            calling_code = country_info.calling_codes()[0]

                            if not sanitized_phone.startswith(calling_code) and not sanitized_phone.startswith(f'+{calling_code}'):
                                final_phone_number = f"{calling_code}{sanitized_phone}"
                            else:
                                final_phone_number = sanitized_phone
                        except (KeyError, IndexError):
                            pass

                    contact_data = schemas.ContactCreate(
                        contact_name=contact_name, phone=final_phone_number,
                        email=get_value(row, 'email'), designation=get_value(row, 'designation'),
                        linkedIn=get_value(row, 'linkedIn'), pan=get_value(row, 'pan')
                    )
                    contacts_for_lead.append(contact_data)

                lead_data = schemas.LeadCreate(
                    company_name=get_value(row, 'company_name') or f"Unnamed Lead Row {index + 2}",
                    assigned_to=assignee_user.username, source=get_value(row, 'source'),
                    created_by="Bulk Upload", contacts=contacts_for_lead,
                    email=get_value(row, 'company_email'), website=get_value(row, 'website'),
                    linkedIn=get_value(row, 'linkedIn_company'), phone_2=get_value(row, 'company_phone_2'),
                    address=get_value(row, 'address'), address_2=get_value(row, 'address_2'),
                    city=get_value(row, 'city'), state=get_value(row, 'state'),
                    pincode=get_value(row, 'pincode'), country=get_value(row, 'country'),
                    turnover=get_value(row, 'turnover'), challenges=get_value(row, 'challenges'),
                    machine_specification=get_value(row, 'machine_specification'),
                    lead_type=get_value(row, 'lead_type'),
                    team_size=str(get_value(row, 'team_size')) if get_value(row, 'team_size') else None,
                    segment=get_value(row, 'segment'), current_system=get_value(row, 'current_system'),
                    remark=get_value(row, 'remark'),
                )

                saved_lead = save_lead(db, lead_data)

                activity_details = get_value(row, 'activity_details')
                if activity_details:
                    activity_type = get_value(row, 'activity_type') or 'Note'
                    activity_payload = schemas.ActivityLogCreate(
                        lead_id=saved_lead.id, details=activity_details,
                        phase="new", activity_type=activity_type
                    )
                    create_activity_log(db, activity_payload)

                success_count += 1
            except Exception as e:
                db.rollback()
                errors.append(f"Row {index + 2}: {str(e)}")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing Excel file: {str(e)}")

    return {
        "status": "Completed",
        "successful_imports": success_count,
        "errors": errors
    }


class LeadDripAssignPayload(schemas.BaseModel):
    lead_id: int
    drip_sequence_id: int

@web_router.post("/leads/assign-drip", status_code=status.HTTP_200_OK)
def assign_drip_sequence_to_lead(
    payload: LeadDripAssignPayload,
    db: Session = Depends(get_db)
):
    lead = get_lead_by_id(db, payload.lead_id)
    drip = get_drip_sequence_by_id(db, payload.drip_sequence_id)

    if not lead or not drip:
        raise HTTPException(status_code=404, detail="Lead or Drip Sequence not found.")

    if not lead.contacts:
        raise HTTPException(status_code=400, detail="Lead has no contacts to send messages to.")

    assignment = assign_drip_to_lead(db, lead.id, drip.id)

    sent_count = 0
    if drip.steps:
        sorted_steps = sorted(drip.steps, key=lambda s: (s.day_to_send, s.sequence_order))
        first_step = sorted_steps[0]
        
        primary_contact = lead.contacts[0]
        first_message = first_step.message
        
        success = False
        if first_message.message_type == 'text':
            if first_message.message_content:
                success = send_whatsapp_message(number=primary_contact.phone, message=first_message.message_content)
        else:
            if first_message.attachment_path:
                caption = first_message.message_content or first_message.message_name
                success = send_whatsapp_message_with_media(
                    number=primary_contact.phone,
                    file_path=first_message.attachment_path,
                    caption=caption,
                    message_type=first_message.message_type
                )

        if success:
            log_sent_drip_message(db, assignment_id=assignment.id, step_id=first_step.id)
            sent_count += 1
            logger.info(f"Sent initial drip message (Step ID: {first_step.id}) to {lead.company_name}")

    return {
        "status": "success",
        "message": f"Drip sequence '{drip.drip_name}' assigned to lead '{lead.company_name}'.",
        "immediate_messages_sent": sent_count
    }



@web_router.post("/activities/schedule", response_model=schemas.ReminderOut)
def schedule_activity_from_web(
    activity_data: ScheduleActivityWeb,
    db: Session = Depends(get_db)
):
    creator = get_user_by_id(db, activity_data.created_by_user_id)
    if not creator:
        raise HTTPException(status_code=404, detail="Creating user not found.")

    if not activity_data.lead_id and not activity_data.proposal_id:
        raise HTTPException(status_code=400, detail="Either lead_id or proposal_id must be provided.")
    
    if activity_data.lead_id:
        parent = get_lead_by_id(db, activity_data.lead_id)
    else:
        parent = db.query(ProposalSent).filter(ProposalSent.id == activity_data.proposal_id).first()
        
    if not parent:
        raise HTTPException(status_code=404, detail="Parent entity not found for scheduling activity.")

    remind_time_local_naive = parse_datetime_from_text(activity_data.details)
    
    try:
        remind_time_local_aware = LOCAL_TIMEZONE.localize(remind_time_local_naive)
        remind_time_utc_aware = remind_time_local_aware.astimezone(pytz.utc)
        remind_time_utc_naive = remind_time_utc_aware.replace(tzinfo=None)
    except Exception as e:
        logger.error(f"Timezone conversion failed: {e}. Falling back to naive time.")
        remind_time_utc_naive = remind_time_local_naive

    message_for_reminder = f"For {parent.company_name}: {activity_data.details}"

    reminder_payload = ReminderCreate(
        lead_id=activity_data.lead_id,
        proposal_id=activity_data.proposal_id,
        remind_time=remind_time_utc_naive,
        message=message_for_reminder, 
        assigned_to=creator.username,
        user_id=creator.id, 
        activity_type=activity_data.activity_type,
        is_hidden_from_activity_log=False
    )

    db_reminder = create_reminder(db, reminder_payload)
    if not db_reminder:
        raise HTTPException(status_code=500, detail="Failed to create reminder.")
        
    if db_reminder.remind_time and db_reminder.remind_time.tzinfo is None:
        db_reminder.remind_time = pytz.utc.localize(db_reminder.remind_time)
    if db_reminder.created_at and db_reminder.created_at.tzinfo is None:
        db_reminder.created_at = pytz.utc.localize(db_reminder.created_at)

    return db_reminder

@web_router.get("/activities/all/{username}", response_model=List[UnifiedActivityOut])
def get_all_activities_for_user(username: str, db: Session = Depends(get_db)):
    user = get_user_by_username(db, username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    is_admin = user.role.lower() == 'admin' if user.role else False

    activities = get_all_unified_activities(db, username=username, is_admin=is_admin)

    processed_activities = []
    for activity in activities:
        activity_data = dict(activity._mapping) 
        
        if activity_data.get('scheduled_for') and activity_data['scheduled_for'].tzinfo is None:
            activity_data['scheduled_for'] = pytz.utc.localize(activity_data['scheduled_for'])
            
        if activity_data.get('created_at') and activity_data['created_at'].tzinfo is None:
            activity_data['created_at'] = pytz.utc.localize(activity_data['created_at'])
            
        processed_activities.append(activity_data)
    
    return processed_activities

@web_router.post("/activities/log", response_model=ActivityLogOut)
def log_activity_from_web(
    activity_data: ActivityLogCreate,
    db: Session = Depends(get_db)
):
    lead = get_lead_by_id(db, activity_data.lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found for activity logging.")

    db_activity = create_activity_log(db, activity_data)

    return db_activity

@web_router.api_route("/attachments/preview/{file_path:path}", methods=["GET", "HEAD"], tags=["Attachments"])
async def preview_attachment(file_path: str):
    full_file_path = os.path.join(UPLOAD_DIRECTORY, file_path)

    if not os.path.isfile(full_file_path):
        logger.error(f"Attachment not found at path: {full_file_path}")
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(path=full_file_path)

@web_router.post("/leads/export-excel")
async def export_leads_to_excel(
    lead_ids: List[int],
    db: Session = Depends(get_db)
):
    if not lead_ids:
        raise HTTPException(status_code=400, detail="No lead IDs provided for export.")

    leads_to_export = db.query(models.Lead).filter(models.Lead.id.in_(lead_ids)).all()

    if not leads_to_export:
        raise HTTPException(status_code=404, detail="None of the provided lead IDs were found.")

    records = []
    for lead in leads_to_export:
        lead_base_info = {
            "company_name": lead.company_name, "assigned_to": lead.assigned_to,
            "source": lead.source, "company_email": lead.email, "website": lead.website,
            "linkedIn_company": lead.linkedIn, "company_phone_2": lead.phone_2,
            "address line": lead.address, "address Line 2": lead.address_2,
            "city": lead.city, "state": lead.state, "country": lead.country,
            "pincode": lead.pincode, "turnover": lead.turnover, "team_size": lead.team_size,
            "segment": lead.segment, "current_system": lead.current_system,
            "challenges": lead.challenges, "machine_specification": lead.machine_specification,
            "lead_type": lead.lead_type, "Remark": lead.remark,
        }

        if lead.contacts:
            for contact in lead.contacts:
                record = lead_base_info.copy()
                record.update({
                    "contact_name": contact.contact_name, "phone": contact.phone,
                    "designation": contact.designation, "email": contact.email,
                    "linkedIn_contact": contact.linkedIn, "pan": contact.pan
                })
                records.append(record)
        else:
            record = lead_base_info.copy()
            record.update({"contact_name": "N/A", "phone": "N/A", "designation": "N/A", "email": "N/A", "linkedIn_contact": "N/A", "pan": "N/A"})
            records.append(record)

    df = pd.DataFrame(records)

    column_order = [
        "company_name", "contact_name", "phone", "assigned_to", "source", "email",
        "designation", "linkedIn_contact", "pan", "company_email", "website", "linkedIn_company", "company_phone_2", "address line",
        "address Line 2", "city", "state", "country", "pincode", "turnover",
        "team_size", "segment", "current_system", "challenges",
        "machine_specification", "lead_type", "Remark"
    ]
    df = df.reindex(columns=column_order)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Leads')
    output.seek(0)

    headers = {'Content-Disposition': 'attachment; filename="leads_export.xlsx"'}

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers
    )


@web_router.post("/activities/scheduled/{reminder_id}/complete", response_model=schemas.StatusMessage)
def mark_scheduled_activity_as_done(
    reminder_id: int,
    payload: MarkActivityDonePayload,
    db: Session = Depends(get_db)
):
    completed_reminder = complete_scheduled_activity(
        db=db,
        reminder_id=reminder_id,
        notes=payload.notes,
        updated_by=payload.updated_by
    )

    if not completed_reminder:
        raise HTTPException(
            status_code=404,
            detail=f"Scheduled activity with ID {reminder_id} not found or is not pending."
        )

    return {"status": "success", "message": f"Activity {reminder_id} has been marked as complete."}

class ReportQuery(BaseModel):
    user_id: int
    start_date: date
    end_date: date

@web_router.post("/reports/user-performance", tags=["Reports"])
def get_user_performance_report(query: ReportQuery, db: Session = Depends(get_db)):
    report_data = generate_user_performance_data(db, query.user_id, query.start_date, query.end_date)
    if not report_data:
        raise HTTPException(status_code=404, detail="User not found or failed to generate data.")
    return report_data

class ReportDateRangeQuery(BaseModel):
    start_date: date
    end_date: date

@web_router.post("/reports/export-summary-excel", tags=["Reports"])
def export_summary_to_excel(query: ReportDateRangeQuery, db: Session = Depends(get_db)):
    users = get_users(db)
    if not users:
        raise HTTPException(status_code=404, detail="No users found in this company to generate a report for.")

    report_rows = []
    for user in users:
        user_data = generate_user_performance_data(db, user.id, query.start_date, query.end_date)
        if user_data and user_data.get("kpi_summary"):
            kpis = user_data["kpi_summary"]
            report_rows.append({
                "User": user.username,
                "New Leads Assigned": kpis.get("new_leads_assigned", 0),
                "Meetings Scheduled": kpis.get("meetings_scheduled", 0),
                "Demos Scheduled": kpis.get("demos_scheduled", 0),
                "Meetings Completed": kpis.get("meetings_completed", 0),
                "Demos Completed": kpis.get("demos_completed", 0),
                "Activities Logged": kpis.get("activities_logged", 0),
                "Deals Won": kpis.get("deals_won", 0),
                "Leads Lost": kpis.get("leads_lost", 0),
                "Conversion Rate (%)": kpis.get("conversion_rate", 0.0),
            })
    
    if not report_rows:
        raise HTTPException(status_code=404, detail="No performance data found for any user in the selected date range.")

    df = pd.DataFrame(report_rows)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='User Performance Summary')
    output.seek(0)

    filename = f"user_performance_summary_{query.start_date}_to_{query.end_date}.xlsx"
    headers = {'Content-Disposition': f'attachment; filename="{filename}"'}

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers
    )

@web_router.put("/meetings/{meeting_id}/reschedule", response_model=EventOut, tags=["Events"])
def api_reschedule_meeting(meeting_id: int, payload: EventReschedulePayload, db: Session = Depends(get_db)):
    updated_meeting = reschedule_meeting(db, meeting_id, payload.start_time, payload.end_time, payload.updated_by)
    if not updated_meeting:
        raise HTTPException(status_code=404, detail="Meeting not found or not in a schedulable state.")
    return updated_meeting

@web_router.put("/meetings/{meeting_id}/reassign", response_model=EventOut, tags=["Events"])
def api_reassign_meeting(meeting_id: int, payload: EventReassignPayload, db: Session = Depends(get_db)):
    user = get_user_by_id(db, payload.assigned_to_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User to assign to not found.")
    updated_meeting = reassign_meeting(db, meeting_id, user, payload.updated_by)
    if not updated_meeting:
        raise HTTPException(status_code=404, detail="Meeting not found or cannot be reassigned.")
    return updated_meeting

@web_router.post("/meetings/{meeting_id}/cancel", response_model=EventOut, tags=["Events"])
def api_cancel_meeting(meeting_id: int, payload: EventCancelPayload, db: Session = Depends(get_db)):
    canceled_meeting = cancel_meeting(db, meeting_id, payload.reason, payload.updated_by)
    if not canceled_meeting:
        raise HTTPException(status_code=404, detail="Meeting not found or cannot be canceled.")
    return canceled_meeting

@web_router.put("/meetings/{meeting_id}/notes", response_model=EventOut, tags=["Events"])
def api_update_meeting_notes(meeting_id: int, payload: EventNotesUpdatePayload, db: Session = Depends(get_db)):
    updated_meeting = update_meeting_notes(db, meeting_id, payload.notes, payload.updated_by)
    if not updated_meeting:
        raise HTTPException(status_code=404, detail="Completed meeting not found.")
    return updated_meeting

@web_router.put("/demos/{demo_id}/reschedule", response_model=DemoOut, tags=["Events"])
def api_reschedule_demo(demo_id: int, payload: EventReschedulePayload, db: Session = Depends(get_db)):
    updated_demo = reschedule_demo(db, demo_id, payload.start_time, payload.end_time, payload.updated_by)
    if not updated_demo:
        raise HTTPException(status_code=404, detail="Demo not found or not in a schedulable state.")
    return updated_demo

@web_router.put("/demos/{demo_id}/reassign", response_model=DemoOut, tags=["Events"])
def api_reassign_demo(demo_id: int, payload: EventReassignPayload, db: Session = Depends(get_db)):
    user = get_user_by_id(db, payload.assigned_to_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User to assign to not found.")
    updated_demo = reassign_demo(db, demo_id, user, payload.updated_by)
    if not updated_demo:
        raise HTTPException(status_code=404, detail="Demo not found or cannot be reassigned.")
    return updated_demo

@web_router.post("/demos/{demo_id}/cancel", response_model=DemoOut, tags=["Events"])
def api_cancel_demo(demo_id: int, payload: EventCancelPayload, db: Session = Depends(get_db)):
    canceled_demo = cancel_demo(db, demo_id, payload.reason, payload.updated_by)
    if not canceled_demo:
        raise HTTPException(status_code=404, detail="Demo not found or cannot be canceled.")
    return canceled_demo

@web_router.put("/demos/{demo_id}/notes", response_model=DemoOut, tags=["Events"])
def api_update_demo_notes(demo_id: int, payload: EventNotesUpdatePayload, db: Session = Depends(get_db)):
    updated_demo = update_demo_notes(db, demo_id, payload.notes, payload.updated_by)
    if not updated_demo:
        raise HTTPException(status_code=404, detail="Completed demo not found.")
    return updated_demo

@web_router.put("/activities/log/{activity_id}", response_model=ActivityLogOut, tags=["Activities"])
def api_update_activity(activity_id: int, payload: ActivityLogUpdate, db: Session = Depends(get_db)):
    updated_activity = update_activity_log(db, activity_id, payload)
    if not updated_activity:
        raise HTTPException(status_code=404, detail="Activity log not found.")
    return updated_activity

@web_router.delete("/activities/log/{activity_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Activities"])
def api_delete_activity(activity_id: int, db: Session = Depends(get_db)):
    success = delete_activity_log(db, activity_id)
    if not success:
        raise HTTPException(status_code=404, detail="Activity log not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@web_router.delete("/activities/scheduled/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Activities"])
def api_cancel_scheduled_activity(reminder_id: int, db: Session = Depends(get_db)):
    reminder = db.query(Reminder).filter(Reminder.id == reminder_id, Reminder.status == 'pending').first()
    if not reminder:
        raise HTTPException(status_code=404, detail="Pending reminder not found.")

    cancellation_log = ActivityLogCreate(
        lead_id=reminder.lead_id,
        details=f"Canceled scheduled activity: {reminder.message}",
        phase="Canceled",
        activity_type=reminder.activity_type
    )
    create_activity_log(db, cancellation_log)

    success = delete_reminder(db, reminder_id)
    if not success:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to cancel the activity.")

    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@web_router.get("/calendar/events/all", tags=["Calendar"])
def get_all_crm_events(db: Session = Depends(get_db)):
    statuses_to_show = ['Scheduled', 'Rescheduled', 'Done']
    all_meetings = db.query(models.Event).options(joinedload(models.Event.lead)).filter(models.Event.phase.in_(statuses_to_show)).all()
    all_demos = db.query(models.Demo).options(joinedload(models.Demo.lead)).filter(models.Demo.phase.in_(statuses_to_show)).all()

    all_users = db.query(User).all()
    user_map = {user.usernumber: user.username for user in all_users}
    events = []

    for meeting in all_meetings:
        aware_start = pytz.utc.localize(meeting.event_time) if meeting.event_time else None
        
        if meeting.event_end_time:
            aware_end = pytz.utc.localize(meeting.event_end_time)
        elif aware_start:
            aware_end = aware_start + timedelta(hours=1)
        else:
            aware_end = None

        if not aware_start or not aware_end: continue

        events.append({
            "id": f"meeting-{meeting.id}",
            "title": f"Meeting: {meeting.lead.company_name if meeting.lead else 'N/A'}",
            "start": aware_start.isoformat(),
            "end": aware_end.isoformat(),
            "extendedProps": { "type": "Meeting", "assignee": meeting.assigned_to, "status": meeting.phase }
        })

    for demo in all_demos:
        aware_start = pytz.utc.localize(demo.start_time) if demo.start_time else None
        
        if demo.event_end_time:
            aware_end = pytz.utc.localize(demo.event_end_time)
        elif aware_start:
            aware_end = aware_start + timedelta(hours=1)
        else:
            aware_end = None
        
        if not aware_start or not aware_end: continue

        assignee_name = user_map.get(demo.assigned_to, 'Unknown User')
        events.append({
            "id": f"demo-{demo.id}",
            "title": f"Demo: {demo.lead.company_name if demo.lead else 'N/A'}",
            "start": aware_start.isoformat(),
            "end": aware_end.isoformat(),
            "extendedProps": { "type": "Demo", "assignee": assignee_name, "status": demo.phase }
        })

    return events


@web_router.get("/calendar/subscribe/{user_id}", tags=["Calendar"])
def subscribe_to_calendar(user_id: int, db: Session = Depends(get_db)):
    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    utc = pytz.utc
    cal = Calendar()

    user_meetings = db.query(models.Event).filter(
        models.Event.assigned_to == user.username,
        models.Event.phase.in_(['Scheduled', 'Rescheduled'])
    ).all()

    user_demos = db.query(models.Demo).filter(
        models.Demo.assigned_to == user.usernumber,
        models.Demo.phase.in_(['Scheduled', 'Rescheduled'])
    ).all()

    for meeting in user_meetings:
        event = ICSEvent()
        event.name = f"CRM Meeting: {meeting.lead.company_name if meeting.lead else 'N/A'}"
        naive_begin = meeting.event_time
        aware_utc_begin = pytz.utc.localize(naive_begin)
        event.begin = aware_utc_begin

        naive_end = meeting.event_end_time or (naive_begin + timedelta(hours=1))
        aware_utc_end = pytz.utc.localize(naive_end)
        event.end = aware_utc_end
        event.description = (f"Type: {meeting.meeting_type or 'Meeting'}\n"
                             f"Lead: {meeting.lead.company_name if meeting.lead else 'N/A'}\n"
                             f"Assigned to: {user.username}\n"
                             f"Status: {meeting.phase}")
        event.uid = f"crm-meeting-{meeting.id}@{user.id}.induscrm.com"
        cal.events.add(event)

    for demo in user_demos:
        event = ICSEvent()
        event.name = f"CRM Demo: {demo.lead.company_name if demo.lead else 'N/A'}"
        naive_begin = demo.start_time
        aware_utc_begin = pytz.utc.localize(naive_begin)
        event.begin = aware_utc_begin

        naive_end = demo.event_end_time or (naive_begin + timedelta(hours=1))
        aware_utc_end = pytz.utc.localize(naive_end)
        event.end = aware_utc_end
        event.description = (f"Type: Demo\n"
                             f"Lead: {demo.lead.company_name if demo.lead else 'N/A'}\n"
                             f"Assigned to: {user.username}\n"
                             f"Status: {demo.phase}")
        event.uid = f"crm-demo-{demo.id}@{user.id}.induscrm.com"
        cal.events.add(event)

    calendar_content = str(cal)

    etag = hashlib.md5(calendar_content.encode('utf-8')).hexdigest()

    headers = {
        'Content-Type': 'text/calendar',
        'Cache-Control': 'must-revalidate, max-age=600',
        'ETag': etag
    }

    return Response(content=calendar_content, headers=headers)

app.include_router(main_router)
app.include_router(web_router, prefix="/web")