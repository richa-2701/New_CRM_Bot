# webhook.py
from fastapi import APIRouter, Request, Response, status,HTTPException,Depends
from app.handlers.message_router import route_message
import logging
from app.models import Lead, Event, Demo
from app.schemas import (
    LeadResponse, UserCreate, UserLogin, UserResponse, TaskOut,
    ActivityLogOut, HistoryItemOut, UserPasswordChange, EventOut,
    DemoOut,EventCreate,
    LeadCreate, LeadUpdateWeb, UserUpdate, MeetingScheduleWeb,
    PostMeetingWeb, DemoScheduleWeb, PostDemoWeb
)
from app.crud import (
    create_user, verify_user, get_user_by_username, change_user_password,
    get_users, get_tasks_by_username, get_activities_by_lead_id, get_lead_history,
    get_all_leads, get_lead_by_id, update_lead, save_lead, get_user_by_id,get_scheduled_meetings,get_scheduled_demos,
    update_user, delete_user, create_event, complete_meeting, complete_demo, is_user_available
)
from sqlalchemy.orm import Session
from app.db import get_db
from datetime import datetime, timedelta

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
    return create_user(db, user)


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
    return {"status": "success", "message": "Password updated successfully"}


@main_router.get("/users", response_model=list[UserResponse], tags=["Users"])
def get_all_users(db: Session = Depends(get_db)):
    """
    Get a list of all users in the system.
    This function now manually constructs the response to avoid serialization errors.
    """
    db_users = get_users(db)
    # Manually create a list of Pydantic UserResponse objects from the SQLAlchemy User objects.
    # This is the most robust way to ensure the response is always correctly formatted.
    response = []
    for user in db_users:
        response.append(UserResponse.model_validate(user))
    return response
# --- END CORRECTION 

# --- Endpoint to update user details ---
@web_router.put("/users/{user_id}", response_model=UserResponse)
def update_user_details(user_id: int, user_data: UserUpdate, db: Session = Depends(get_db)):
    updated_user = update_user(db, user_id, user_data)
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
    return updated_user

# --- Endpoint to delete a user ---
@web_router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_user(user_id: int, db: Session = Depends(get_db)):
    success = delete_user(db, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="User not found")
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
        created_lead = save_lead(db, lead_data, created_by=lead_data.created_by, assigned_name=lead_data.assigned_to)
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