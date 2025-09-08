# webhook.py
from fastapi import APIRouter, Request, Response, status,HTTPException,Depends,UploadFile, File, Form
from app.handlers.message_router import route_message
import logging
from fastapi.responses import StreamingResponse
import httpx
import shutil
import pandas as pd
import uuid
from app import schemas
import os
import re
from countryinfo import CountryInfo
import io
from typing import Optional, List
from app import models
from app.models import Lead, Event, Demo
from app.schemas import (
    LeadResponse, ScheduleActivityWeb, ReminderCreate, UserCreate, UserLogin, UserResponse, TaskOut,
    ActivityLogOut, HistoryItemOut, UserPasswordChange, EventOut,ActivityLogCreate,
    DemoOut,EventCreate,MessageMasterCreate, MessageMasterUpdate, MessageMasterOut,
    DripSequenceCreate,UnifiedActivityOut, DripSequenceOut, DripSequenceListOut,
    LeadCreate, LeadUpdateWeb, UserUpdate, MeetingScheduleWeb,
    PostMeetingWeb, DemoScheduleWeb,MarkActivityDonePayload, PostDemoWeb,ReminderOut,
    EventReschedulePayload, EventReassignPayload, EventCancelPayload, 
    EventNotesUpdatePayload, ActivityLogUpdate
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
    update_activity_log, delete_activity_log, delete_reminder
)
from sqlalchemy.orm import Session
from app.db import get_db
from app.gpt_parser import parse_datetime_from_text 
from datetime import datetime, timedelta
from app.message_sender import send_whatsapp_message 
from app.crud import assign_drip_to_lead, log_sent_drip_message


UPLOAD_DIRECTORY = "uploads"

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

main_router = APIRouter()
web_router = APIRouter()

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
    # This dictionary can be expanded with more countries as needed
}

def get_country_phone_code(country_name: str) -> Optional[str]:
    """Finds the phone code for a given country name from the mapping."""
    if not country_name:
        return None
    return COUNTRY_PHONE_CODES.get(country_name.lower().strip())


# --- USER MANAGEMENT ROUTES (FOR BOTH WEB AND APP) ---

@main_router.post("/register", response_model=UserResponse, tags=["Authentication"])
def register_user(user: UserCreate, db: Session = Depends(get_db)):
    existing = get_user_by_username(db, user.username)
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    new_user = create_user(db, user)
    db.commit()
    db.refresh(new_user)
    
    return new_user


@main_router.post("/login", response_model=UserResponse, tags=["Authentication"])
def login_user(user: UserLogin, db: Session = Depends(get_db)):
    authenticated_user = verify_user(db, user.username, user.password)
    if not authenticated_user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return authenticated_user

@main_router.post("/change-password", tags=["Users"])
def change_password(password_data: UserPasswordChange, db: Session = Depends(get_db)):
    updated_user = change_user_password(db, password_data)
    if not updated_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or old password")
    db.commit()
    return {"status": "success", "message": "Password updated successfully"}


@main_router.get("/users", response_model=list[UserResponse], tags=["Users"])
def get_all_users(db: Session = Depends(get_db)):
    """
    Get a list of all users in the system.
    This function now manually constructs the response to avoid serialization errors.
    """
    db_users = get_users(db)
    response = []
    for user in db_users:
        response.append(UserResponse.model_validate(user))
    return response

@web_router.put("/users/{user_id}", response_model=UserResponse)
def update_user_details(user_id: int, user_data: UserUpdate, db: Session = Depends(get_db)):
    updated_user = update_user(db, user_id, user_data)
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
    db.commit()
    db.refresh(updated_user)
    return updated_user

# --- Endpoint to delete a user ---
@web_router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_user(user_id: int, db: Session = Depends(get_db)):
    success = delete_user(db, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="User not found")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# --- LEAD, TASK, and HISTORY Routes (Mainly for WhatsApp Bot and App) ---

@main_router.get("/leads/{user_id}", response_model=list[LeadResponse], tags=["Leads & History"])
async def get_leads_by_user_id(user_id: str, db: Session = Depends(get_db)):
    leads = db.query(Lead).filter(Lead.assigned_to == user_id).all()
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


# --- WHATSAPP WEBHOOK AND APP-MESSAGE ROUTES ---

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
    if data.get("type") != "message":
        return Response(status_code=status.HTTP_200_OK)
    if "message" not in data or not isinstance(data["message"], dict):
        return Response(status_code=status.HTTP_200_OK)
    msg = data.get("message", {})
    if msg.get("type") != "text":
        return Response(status_code=status.HTTP_200_OK)
    sender_phone = data.get("user", {}).get("phone")
    message_text = msg.get("text", "").strip()
    reply_url = data.get("reply", "")
    source = data.get("source", "whatsapp")
    if not all([sender_phone, message_text, reply_url]):
        return Response(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content="Missing critical fields")
    response_from_handler = await route_message(sender_phone, message_text, reply_url, source)
    return response_from_handler


@main_router.post("/app", tags=["WhatsApp & App Integration"])
async def receive_app_message(req: Request):
    try:
        data = await req.json()
    except Exception as e:
        return {"status": "error", "reply": "Invalid JSON"}
    logger.info(f"📱 Incoming App Payload: {data}")
    sender_phone = data.get("user_phone") or data.get("phone")
    message_text = data.get("message", "").strip()
    if not all([sender_phone, message_text]):
        return {"status": "error", "reply": f"Missing fields: user_phone and/or message"}
    response_from_handler = await route_message(sender_phone, message_text, "", "app")
    return response_from_handler


# --- ALL ROUTES FOR THE WEB APPLICATION FRONTEND ---

# --- Web/Leads Endpoints ---
@web_router.post("/leads", response_model=LeadResponse)
def create_lead_from_web(lead_data: LeadCreate, db: Session = Depends(get_db)):
    try:
        created_lead = save_lead(db, lead_data)
        return created_lead
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")

@web_router.get("/leads", response_model=list[LeadResponse])
def get_all_leads_for_web(db: Session = Depends(get_db)):
    """
    Get all leads to display in the web UI.
    This function now manually constructs the response to avoid serialization errors.
    """
    
    db_leads_data = get_all_leads_with_last_activity(db)
    # Manually create a list of Pydantic LeadResponse objects.
    response = []
    for lead_data in db_leads_data:
        # Pydantic's model_validate will automatically handle the nested 'last_activity'
        response.append(LeadResponse.model_validate(lead_data))
        
    return response

@web_router.get("/leads/{lead_id}", response_model=LeadResponse)
def get_single_lead_for_web(lead_id: int, db: Session = Depends(get_db)):
    lead = get_lead_by_id(db, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead

@web_router.get("/meetings", response_model=list[EventOut])
def get_all_scheduled_meetings(db: Session = Depends(get_db)):
    meetings = get_scheduled_meetings(db)
    return [EventOut.model_validate(m) for m in meetings]

@web_router.get("/meetings/all", response_model=list[EventOut])
def get_every_meeting(db: Session = Depends(get_db)):
    """Fetches a list of ALL meetings, including completed ones."""
    meetings_from_db = get_all_meetings(db)
    
    # --- THIS IS THE PERMANENT FIX ---
    # Manually construct the response to ensure all fields are included,
    # bypassing any silent Pydantic serialization issues.
    response = []
    for meeting in meetings_from_db:
        response.append(
            EventOut(
                id=meeting.id,
                lead_id=meeting.lead_id,
                assigned_to=meeting.assigned_to,
                event_type=meeting.event_type,
                event_time=meeting.event_time,
                event_end_time=meeting.event_end_time,
                created_by=meeting.created_by,
                remark=meeting.remark,
                phase=meeting.phase,
                created_at=meeting.created_at
            )
        )
    return response

@web_router.get("/demos", response_model=list[DemoOut])
def get_all_scheduled_demos(db: Session = Depends(get_db)):
    demos = get_scheduled_demos(db)
    return [DemoOut.model_validate(d) for d in demos]

@web_router.get("/demos/all", response_model=list[DemoOut])
def get_every_demo(db: Session = Depends(get_db)):
    """Fetches a list of ALL demos, including completed ones."""
    demos_from_db = get_all_demos(db)

    # --- APPLY THE SAME PERMANENT FIX FOR DEMOS ---
    response = []
    for demo in demos_from_db:
        response.append(
            DemoOut(
                id=demo.id,
                lead_id=demo.lead_id,
                scheduled_by=demo.scheduled_by,
                assigned_to=demo.assigned_to,
                start_time=demo.start_time,
                event_end_time=demo.event_end_time,
                phase=demo.phase,
                remark=demo.remark,
                created_at=demo.created_at,
                updated_at=demo.updated_at
            )
        )
    return response

@web_router.post("/meetings/schedule", response_model=EventOut)
def schedule_meeting_from_web(meeting_data: MeetingScheduleWeb, db: Session = Depends(get_db)):
    assignee = get_user_by_id(db, meeting_data.assigned_to_user_id)
    creator = get_user_by_id(db, meeting_data.created_by_user_id)
    if not assignee or not creator:
        raise HTTPException(status_code=404, detail="Assignee or Creator user not found")
    conflicting_event = is_user_available(db, assignee.username, assignee.usernumber, meeting_data.start_time, meeting_data.end_time)
    if conflicting_event:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"User '{assignee.username}' is already booked at this time.")
    event_schema = EventCreate(lead_id=meeting_data.lead_id, assigned_to=assignee.username, event_type="Meeting", event_time=meeting_data.start_time, event_end_time=meeting_data.end_time, created_by=creator.username, remark="Scheduled via Web UI")
    
    # This is the new block of code that updates the lead's status
    update_lead_status(
        db,
        lead_id=meeting_data.lead_id,
        status="Meeting Scheduled",
        updated_by=creator.username
    )
    return create_event(db, event_schema)

@web_router.post("/meetings/complete", response_model=schemas.StatusMessage) # Using a generic response schema is good practice
def post_meeting_from_web(data: PostMeetingWeb, db: Session = Depends(get_db)):
    event = complete_meeting(db=db, meeting_id=data.meeting_id, notes=data.notes, updated_by=data.updated_by)
    if not event:
        raise HTTPException(status_code=404, detail=f"Meeting with ID {data.meeting_id} not found or already completed.")
    return {"status": "success", "message": f"Meeting {data.meeting_id} has been marked as complete."}

@web_router.post("/demos/schedule", response_model=DemoOut)
def schedule_demo_from_web(demo_data: DemoScheduleWeb, db: Session = Depends(get_db)):
    assignee = get_user_by_id(db, demo_data.assigned_to_user_id)
    creator = get_user_by_id(db, demo_data.created_by_user_id)
    lead = get_lead_by_id(db, demo_data.lead_id)
    if not all([assignee, creator, lead]):
        raise HTTPException(status_code=404, detail="Assignee, Creator, or Lead not found")
    conflicting_event = is_user_available(db, assignee.username, assignee.usernumber, demo_data.start_time, demo_data.end_time)
    if conflicting_event:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"User '{assignee.username}' is already booked at this time.")
    new_demo = Demo(lead_id=lead.id, assigned_to=assignee.usernumber, scheduled_by=creator.username, start_time=demo_data.start_time, event_end_time=demo_data.end_time)
    db.add(new_demo)
    db.commit()
    db.refresh(new_demo)
    update_lead_status(
        db,
        lead_id=demo_data.lead_id,
        status="Demo Scheduled",
        updated_by=creator.username
    )
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
def api_create_message(message_data: MessageMasterCreate, db: Session = Depends(get_db)):
    return create_message(db, message_data)

@web_router.get("/messages", response_model=list[MessageMasterOut])
def api_get_all_messages(db: Session = Depends(get_db)):
    return get_all_messages(db)

@web_router.put("/messages/{message_id}", response_model=MessageMasterOut)
def api_update_message(message_id: int, message_data: MessageMasterUpdate, db: Session = Depends(get_db)):
    updated_message = update_message(db, message_id, message_data)
    if not updated_message:
        raise HTTPException(status_code=404, detail="Message not found")
    return updated_message

@web_router.delete("/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
def api_delete_message(message_id: int, db: Session = Depends(get_db)):
    if not delete_message(db, message_id):
        raise HTTPException(status_code=404, detail="Message not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- NEW: Web/Drip Sequence Endpoints ---
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
    """
    Fetches a list of all pending reminders (scheduled activities).
    """
    reminders = get_pending_reminders(db) # Correctly uses the new function name
    return [ReminderOut.model_validate(rem) for rem in reminders]
# --- END CORRECTION ---

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
        # Create a unique filename to prevent overwrites
        unique_id = uuid.uuid4().hex
        # Keep the original file extension
        file_extension = os.path.splitext(file.filename)[1]
        attachment_filename = f"{unique_id}{file_extension}"
        
        file_path = os.path.join(UPLOAD_DIRECTORY, attachment_filename)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

    activity_data = ActivityLogCreate(
        lead_id=lead.id,
        phase=lead.status,  # Or any relevant phase
        details=details
    )
    
    # We need a way to add attachment_path to the DB model, let's adapt the crud function
    # For now, let's create the object and set it manually.
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
    """
    Accepts an Excel file, creates leads with ALL provided details by normalizing
    column headers, and logs an initial activity for each lead if provided.
    
    MODIFIED LOGIC:
    - All fields are now optional except for 'assigned_to'.
    - A contact record is only created if at least a contact_name or phone is present.
    - If a 'country' is provided, its country code will be automatically 
      prefixed to the contact's phone number if not already present.
    """
    success_count = 0
    errors = []
    
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload an Excel file.")
    
    try:
        df = pd.read_excel(file.file, dtype=str).fillna('')
        
        column_map = {col.strip().lower(): col for col in df.columns}

        def get_value(row, cleaned_name):
            """A safe way to get a value from a row using the clean name."""
            original_name = column_map.get(cleaned_name)
            if original_name and row[original_name] and str(row[original_name]).strip():
                return str(row[original_name]).strip()
            return None
        
        for index, row in df.iterrows():
            try:
                # 1. VALIDATION: Only 'assigned_to' is mandatory.
                assignee_name = get_value(row, 'assigned_to')
                if not assignee_name:
                    raise ValueError("The required field 'assigned_to' is missing or empty.")

                assignee_user = get_user_by_name(db, assignee_name)
                if not assignee_user:
                    raise ValueError(f"Assigned user '{assignee_name}' not found in the database.")
                
                # 2. Prepare Contact Data (if any exists)
                contacts_for_lead = []
                contact_name = get_value(row, 'contact_name')
                phone_number = get_value(row, 'phone')

                # Only proceed to create a contact if there's actual contact information to save.
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
                            # If country name is invalid, just use the original phone number
                            pass 

                    contact_data = schemas.ContactCreate(
                        contact_name=contact_name,
                        phone=final_phone_number,
                        email=get_value(row, 'email'),
                        designation=get_value(row, 'designation'),
                    )
                    contacts_for_lead.append(contact_data)
                
                # 3. Build the main Lead schema
                lead_data = schemas.LeadCreate(
                    company_name=get_value(row, 'company_name') or f"Unnamed Lead Row {index + 2}", # Provide a default if company name is also blank
                    assigned_to=assignee_user.username,
                    source=get_value(row, 'source'),
                    created_by="Bulk Upload",
                    contacts=contacts_for_lead, # Use the list we prepared
                    
                    # All optional fields are read safely
                    email=get_value(row, 'company_email'),
                    phone_2=get_value(row, 'company_phone_2'),
                    address=get_value(row, 'address'),
                    address_2=get_value(row, 'address_2'),
                    city=get_value(row, 'city'),
                    state=get_value(row, 'state'),
                    pincode=get_value(row, 'pincode'),
                    country=get_value(row, 'country'),
                    turnover=get_value(row, 'turnover'),
                    challenges=get_value(row, 'challenges'),
                    machine_specification=get_value(row, 'machine_specification'),
                    lead_type=get_value(row, 'lead_type'),
                    team_size=get_value(row, 'team_size'),
                    segment=get_value(row, 'segment'),
                    current_system=get_value(row, 'current_system'),
                    remark=get_value(row, 'remark'),
                )
                
                # 4. Save the lead
                saved_lead = save_lead(db, lead_data)
                
                # 5. Log activity if details are present
                activity_details = get_value(row, 'activity_details')
                if activity_details:
                    activity_type = get_value(row, 'activity_type') or 'Note'
                    activity_payload = schemas.ActivityLogCreate(
                        lead_id=saved_lead.id,
                        details=activity_details,
                        phase="new",
                        activity_type=activity_type
                    )
                    create_activity_log(db, activity_payload)

                success_count += 1
            except Exception as e:
                # Rollback the session in case of an error within the loop to allow subsequent rows to be processed
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

    # Create the assignment record in the database
    assignment = assign_drip_to_lead(db, lead_id=lead.id, drip_sequence_id=drip.id)
    
    # --- Handle Day 0 Immediate Send ---
    day_zero_steps = [step for step in drip.steps if step.day_to_send == 0]
    
    sent_count = 0
    if day_zero_steps:
        primary_contact = lead.contacts[0]
        for step in day_zero_steps:
            message_content = step.message.message_content
            if message_content:
                success = send_whatsapp_message(None, primary_contact.phone, message_content)
                if success:
                    log_sent_drip_message(db, assignment_id=assignment.id, step_id=step.id)
                    sent_count += 1
    
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
    """
    Schedules a new activity (reminder) directly from the web application.
    """
    creator = get_user_by_id(db, activity_data.created_by_user_id)
    if not creator:
        raise HTTPException(status_code=404, detail="Creating user not found.")

    # Use the gpt_parser to extract the time from the details string
    remind_time = parse_datetime_from_text(activity_data.details)
    
    # The message for the reminder is just the details, without time info
    message_for_reminder = activity_data.details # The bot can parse this later if needed

    reminder_payload = ReminderCreate(
        lead_id=activity_data.lead_id,
        remind_time=remind_time,
        message=message_for_reminder,
        assigned_to=creator.username,
        user_id=creator.id,
        activity_type=activity_data.activity_type
    )

    db_reminder = create_reminder(db, reminder_payload)
    if not db_reminder:
        raise HTTPException(status_code=500, detail="Failed to create reminder.")
        
    return db_reminder



@web_router.get("/activities/all/{username}", response_model=List[UnifiedActivityOut])
def get_all_activities_for_user(username: str, db: Session = Depends(get_db)):
    """
    Fetches a unified list of all logged and scheduled activities for a user.
    This is the endpoint that the new Activity Management page calls.
    """
    user = get_user_by_username(db, username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if the user is an admin
    is_admin = user.role.lower() == 'admin' if user.role else False
    
    # Call the existing CRUD function to get the data
    activities = get_all_unified_activities(db, username=username, is_admin=is_admin)
    
    return activities

@web_router.post("/activities/log", response_model=ActivityLogOut)
def log_activity_from_web(
    activity_data: ActivityLogCreate,
    db: Session = Depends(get_db)
):
    """
    Logs a completed activity directly from the web application.
    """
    lead = get_lead_by_id(db, activity_data.lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found for activity logging.")
    
    db_activity = create_activity_log(db, activity_data)
    
    return db_activity

@web_router.get("/attachments/preview/{file_path:path}")
async def preview_attachment(file_path: str):
    """
    A proxy endpoint to serve attachment files and bypass Ngrok browser warnings in iframes.
    """
    # Construct the internal URL to the static file
    internal_file_url = f"http://127.0.0.1:8000/attachments/{file_path}"
    
    # Use an async HTTP client to fetch the file
    async with httpx.AsyncClient() as client:
        try:
            # The header is not strictly needed for an internal call but is good practice
            headers = {"ngrok-skip-browser-warning": "true"}
            response = await client.get(internal_file_url, headers=headers, follow_redirects=True)
            
            # If the file was found internally, stream it back to the user
            if response.status_code == 200:
                return StreamingResponse(response.iter_bytes(), media_type=response.headers.get("Content-Type"))
            else:
                # If the file wasn't found, return the same status code
                return Response(status_code=response.status_code)
        except httpx.RequestError as e:
            logger.error(f"Failed to proxy attachment {file_path}: {e}")
            raise HTTPException(status_code=500, detail="Could not retrieve the file.")
        



@web_router.post("/meetings/complete")
def post_meeting_from_web(data: PostMeetingWeb, db: Session = Depends(get_db)):
    """
    Handles completing a meeting from the web UI.
    Receives the meeting_id, notes, and the user who updated it.
    """
    event = complete_meeting(
        db=db, 
        meeting_id=data.meeting_id, 
        notes=data.notes, 
        updated_by=data.updated_by
    )
    
    if not event:
        # This handles cases where the meeting ID is invalid or already completed
        raise HTTPException(
            status_code=404, 
            detail=f"Meeting with ID {data.meeting_id} not found or already completed."
        )
        
    return {"status": "success", "message": f"Meeting {data.meeting_id} has been marked as complete."}

@web_router.post("/leads/export-excel")
async def export_leads_to_excel(
    lead_ids: List[int],  # We will send the list of IDs from the frontend
    db: Session = Depends(get_db)
):
    """
    Exports specified leads to an Excel file. If a lead has multiple contacts,
    it creates a separate row for each contact, duplicating the lead's info.
    """
    if not lead_ids:
        raise HTTPException(status_code=400, detail="No lead IDs provided for export.")

    # Fetch all the leads corresponding to the IDs from the database
    leads_to_export = db.query(models.Lead).filter(models.Lead.id.in_(lead_ids)).all()

    if not leads_to_export:
        raise HTTPException(status_code=404, detail="None of the provided lead IDs were found.")

    # Prepare a list of dictionaries to build the DataFrame
    records = []
    for lead in leads_to_export:
        # This is the base information for the lead that will be repeated for each contact
        lead_base_info = {
            "company_name": lead.company_name,
            "assigned_to": lead.assigned_to,
            "source": lead.source,
            "company_email": lead.email,
            "company_phone_2": lead.phone_2,
            "address line": lead.address,
            "address Line 2": lead.address_2,
            "city": lead.city,
            "state": lead.state,
            "country": lead.country,
            "pincode": lead.pincode,
            "turnover": lead.turnover,
            "team_size": lead.team_size,
            "segment": lead.segment,
            "current_system": lead.current_system,
            "challenges": lead.challenges,
            "machine_specification": lead.machine_specification,
            "lead_type": lead.lead_type,
            "Remark": lead.remark,
        }

        if lead.contacts:
            # If contacts exist, create a new row for each one
            for contact in lead.contacts:
                record = lead_base_info.copy()
                record.update({
                    "contact_name": contact.contact_name,
                    "phone": contact.phone,
                    "designation": contact.designation,
                    "email": contact.email, # Contact's specific email
                })
                records.append(record)
        else:
            # If a lead has no contacts, still include it in the export
            record = lead_base_info.copy()
            record.update({"contact_name": "N/A", "phone": "N/A", "designation": "N/A", "email": "N/A"})
            records.append(record)

    df = pd.DataFrame(records)

    # Define the exact column order you requested for the final Excel file
    column_order = [
        "company_name", "contact_name", "phone", "assigned_to", "source", "email",
        "designation", "company_email", "company_phone_2", "address line",
        "address Line 2", "city", "state", "country", "pincode", "turnover",
        "team_size", "segment", "current_system", "challenges",
        "machine_specification", "lead_type", "Remark"
    ]
    # Reorder the DataFrame to match the desired output
    df = df.reindex(columns=column_order)

    # Create an in-memory binary stream to save the Excel file
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Leads')
    output.seek(0)

    # Set headers to tell the browser to download the file
    headers = {'Content-Disposition': 'attachment; filename="leads_export.xlsx"'}

    # Stream the file back to the client
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
    """
    Handles completing a scheduled activity (a reminder) from the web UI.
    Receives the reminder_id, notes, and the user who updated it.
    """
    completed_reminder = complete_scheduled_activity(
        db=db, 
        reminder_id=reminder_id, 
        notes=payload.notes, 
        updated_by=payload.updated_by
    )
    
    if not completed_reminder:
        # This handles cases where the reminder ID is invalid or the activity was already completed.
        raise HTTPException(
            status_code=404, 
            detail=f"Scheduled activity with ID {reminder_id} not found or is not pending."
        )
        
    return {"status": "success", "message": f"Activity {reminder_id} has been marked as complete."}

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

# --- NEW: Endpoints for Managing Demos ---

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
    
# --- NEW: Endpoints for Managing Activities ---

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
    success = delete_reminder(db, reminder_id)
    if not success:
        raise HTTPException(status_code=404, detail="Pending reminder not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

