# webhook.py
from fastapi import APIRouter, Request, Response, status,HTTPException,Depends,UploadFile, File, Form
from app.handlers.message_router import route_message
import logging
import shutil
import pandas as pd
import uuid
from app import schemas
import os
from typing import Optional
from app import models
from app.models import Lead, Event, Demo
from app.schemas import (
    LeadResponse, UserCreate, UserLogin, UserResponse, TaskOut,
    ActivityLogOut, HistoryItemOut, UserPasswordChange, EventOut,ActivityLogCreate,
    DemoOut,EventCreate,MessageMasterCreate, MessageMasterUpdate, MessageMasterOut,
    DripSequenceCreate, DripSequenceOut, DripSequenceListOut,
    LeadCreate, LeadUpdateWeb, UserUpdate, MeetingScheduleWeb,
    PostMeetingWeb, DemoScheduleWeb, PostDemoWeb,ReminderOut
)
from app.crud import (
    create_user, verify_user, get_user_by_username, change_user_password,
    get_users, get_tasks_by_username, get_activities_by_lead_id, get_lead_history,
    get_all_leads, get_lead_by_id, update_lead, save_lead, get_user_by_id,get_scheduled_meetings,get_scheduled_demos,
    update_user, delete_user, create_event, complete_meeting, complete_demo, is_user_available,get_user_by_name,
    create_message, get_all_messages, get_message_by_id, update_message, delete_message,get_pending_discussion_reminders,
    create_drip_sequence, get_all_drip_sequences, get_drip_sequence_by_id, update_drip_sequence, delete_drip_sequence
)
from sqlalchemy.orm import Session
from app.db import get_db
from datetime import datetime, timedelta
from app.message_sender import send_whatsapp_message 
from app.crud import assign_drip_to_lead, log_sent_drip_message


UPLOAD_DIRECTORY = "uploads"

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

main_router = APIRouter()
web_router = APIRouter()


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
    db_leads = get_all_leads(db)
    # Manually create a list of Pydantic LeadResponse objects.
    response = []
    for lead in db_leads:
        response.append(LeadResponse.model_validate(lead))
    return response

@web_router.get("/leads/{lead_id}", response_model=LeadResponse)
def get_single_lead_for_web(lead_id: int, db: Session = Depends(get_db)):
    lead = get_lead_by_id(db, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead

@web_router.get("/meetings", response_model=list[EventOut], tags=["Web Application"])
def get_all_scheduled_meetings(db: Session = Depends(get_db)):
    """
    Fetches a list of all meetings with a 'Scheduled' status for the web dashboard.
    """
    meetings = get_scheduled_meetings(db)
    # Use model_validate to ensure correct serialization
    return [EventOut.model_validate(meeting) for meeting in meetings]

# --- NEW ENDPOINT FOR SCHEDULED DEMOS ---
@web_router.get("/demos", response_model=list[DemoOut], tags=["Web Application"])
def get_all_scheduled_demos(db: Session = Depends(get_db)):
    """
    Fetches a list of all demos with a 'Scheduled' status for the web dashboard.
    """
    demos = get_scheduled_demos(db)
    # Use model_validate to ensure correct serialization
    return [DemoOut.model_validate(demo) for demo in demos]

@web_router.put("/leads/{lead_id}", response_model=LeadResponse)
def update_lead_from_web(lead_id: int, lead_data: LeadUpdateWeb, db: Session = Depends(get_db)):
    db_lead = update_lead(db, lead_id, lead_data)
    if not db_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return db_lead

# --- Web/Meeting Endpoints ---
@web_router.post("/meetings/schedule", response_model=EventOut)
def schedule_meeting_from_web(meeting_data: MeetingScheduleWeb, db: Session = Depends(get_db)):
    assignee = get_user_by_id(db, meeting_data.assigned_to_user_id)
    creator = get_user_by_id(db, meeting_data.created_by_user_id)
    if not assignee or not creator:
        raise HTTPException(status_code=404, detail="Assignee or Creator not found")
    if is_user_available(db, assignee.username, assignee.usernumber, meeting_data.start_time, meeting_data.end_time):
        raise HTTPException(status_code=409, detail=f"Conflict: User {assignee.username} is unavailable.")
    event_schema = EventCreate(lead_id=meeting_data.lead_id, assigned_to=assignee.username, event_type="Meeting", event_time=meeting_data.start_time, event_end_time=meeting_data.end_time, created_by=creator.username, remark="Scheduled via Web UI")
    return create_event(db, event_schema)

@web_router.post("/meetings/complete")
def post_meeting_from_web(data: PostMeetingWeb, db: Session = Depends(get_db)):
    event = complete_meeting(db, data.meeting_id, data.notes, data.updated_by)
    if not event:
        raise HTTPException(status_code=404, detail="Meeting not found or already completed.")
    return {"status": "success", "message": f"Meeting {data.meeting_id} marked as complete."}
    
# --- Web/Demo Endpoints ---
@web_router.post("/demos/schedule", response_model=DemoOut)
def schedule_demo_from_web(demo_data: DemoScheduleWeb, db: Session = Depends(get_db)):
    assignee = get_user_by_id(db, demo_data.assigned_to_user_id)
    creator = get_user_by_id(db, demo_data.created_by_user_id)
    lead = get_lead_by_id(db, demo_data.lead_id)
    if not all([assignee, creator, lead]):
        raise HTTPException(status_code=404, detail="Assignee, Creator, or Lead not found")
    if is_user_available(db, assignee.username, assignee.usernumber, demo_data.start_time, demo_data.end_time):
        raise HTTPException(status_code=409, detail=f"Conflict: User {assignee.username} is unavailable at this time.")
    new_demo = Demo(lead_id=lead.id, assigned_to=assignee.usernumber, scheduled_by=creator.username, start_time=demo_data.start_time, event_end_time=demo_data.end_time)
    db.add(new_demo)
    db.commit()
    db.refresh(new_demo)
    return new_demo
    
@web_router.post("/demos/complete")
def post_demo_from_web(data: PostDemoWeb, db: Session = Depends(get_db)):
    demo = complete_demo(db, data.demo_id, data.notes, data.updated_by)
    if not demo:
        raise HTTPException(status_code=404, detail="Demo not found or already completed.")
    return {"status": "success", "message": f"Demo {data.demo_id} marked as complete."}



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


@web_router.get("/discussions/pending", response_model=list[ReminderOut])
def get_pending_discussions(db: Session = Depends(get_db)):
    """
    Fetches a list of all reminders for discussions that are currently scheduled (pending).
    """
    reminders = get_pending_discussion_reminders(db)
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
    Accepts an Excel file, extracts lead data, and creates leads in the database.
    Required columns in Excel: company_name, contact_name, phone, assigned_to, source
    """
    success_count = 0
    errors = []

    # Check for valid file type
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload an Excel file (.xlsx or .xls).")

    try:
        # Use pandas to read the Excel file directly from the upload stream
        df = pd.read_excel(file.file)

        # Iterate through each row in the Excel file
        for index, row in df.iterrows():
            try:
                # --- Data Validation ---
                required_columns = ['company_name', 'contact_name', 'phone', 'assigned_to', 'source']
                for col in required_columns:
                    if col not in row or pd.isna(row[col]):
                        raise ValueError(f"Missing required value for '{col}'")
                
                assignee_name = row['assigned_to']
                assignee_user = get_user_by_name(db, assignee_name)
                if not assignee_user:
                    raise ValueError(f"Assigned user '{assignee_name}' not found in the system.")
                
                # --- Prepare Lead Data using Pydantic Schemas ---
                contact_data = schemas.ContactCreate(
                    contact_name=str(row['contact_name']),
                    phone=str(row['phone']),
                    email=str(row['email']) if 'email' in row and pd.notna(row['email']) else None,
                    designation=str(row['designation']) if 'designation' in row and pd.notna(row['designation']) else None,
                )

                lead_data = schemas.LeadCreate(
                    company_name=str(row['company_name']),
                    assigned_to=assignee_user.username,
                    source=str(row['source']),
                    created_by="Bulk Upload", # Or get current user if you have auth context
                    contacts=[contact_data],
                    # Add any other optional fields from your Excel sheet
                    remark=str(row['remark']) if 'remark' in row and pd.notna(row['remark']) else None,
                    lead_type=str(row['lead_type']) if 'lead_type' in row and pd.notna(row['lead_type']) else None,
                )

                # --- Save the lead using your existing CRUD function ---
                save_lead(db, lead_data)
                success_count += 1

            except Exception as e:
                # Log the error for this specific row
                errors.append(f"Row {index + 2}: {str(e)}") # +2 to account for header and 0-indexing

    except Exception as e:
        # This catches errors with reading the file itself
        raise HTTPException(status_code=400, detail=f"Error processing Excel file: {str(e)}")

    # Return a detailed summary
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