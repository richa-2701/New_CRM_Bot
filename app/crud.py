# app/crud.py
from datetime import datetime
from typing import Optional, Union
from sqlalchemy.orm import Session
from sqlalchemy import func, union_all, literal_column
from app import models, schemas
from app.models import User, Event, ActivityLog, Lead, AssignmentLog, Demo
import re

def create_user(db: Session, user: schemas.UserCreate):
    # We are storing the password as plain text, as requested.
    db_user = models.User(
        username=user.username,
        usernumber=user.usernumber,
        email=user.email,
        department=user.department,
        password=user.password, # Storing the string directly
        role=user.role
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


# --- NEW: Function to get a user by their ID ---
def get_user_by_id(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()

def get_users(db: Session):
    """
    Retrieves a list of all users from the database, ordered by username.
    """
    return db.query(models.User).order_by(models.User.username).all()


def get_user_by_username(db: Session, username: str):
    return db.query(models.User).filter(models.User.username == username).first()


def get_user_by_phone(db: Session, phone: Union[str, int]):
    """
    Safely retrieves a user by their phone number, whether it's passed as a string or an integer.
    """
    # Convert the input to a string to safely perform string operations.
    phone_str = str(phone)
    return db.query(User).filter(User.usernumber == phone_str.strip()).first()

def verify_user(db: Session, username: str, password: str) -> Optional[models.User]:
    # Get the user from the database
    user = get_user_by_username(db, username)
    
    # Check if the user exists and if the provided password matches the stored password.
    if user and user.password == password:
        return user
    
    # If the user doesn't exist or the password doesn't match, return None.
    return None

def change_user_password(db: Session, user_data: schemas.UserPasswordChange) -> Optional[models.User]:
    # This now uses our corrected verify_user function
    user_to_update = verify_user(db, user_data.username, user_data.old_password)
    if not user_to_update:
        return None

    # We store the new password as plain text
    user_to_update.password = user_data.new_password
    db.commit()
    db.refresh(user_to_update)
    return user_to_update

# --- NEW: Function to update a user's details from the web ---
def update_user(db: Session, user_id: int, user_data: schemas.UserUpdate) -> Optional[models.User]:
    db_user = get_user_by_id(db, user_id)
    if not db_user:
        return None
    
    update_data = user_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_user, key, value)
        
    db.commit()
    db.refresh(db_user)
    return db_user

# --- NEW: Function to delete a user ---
def delete_user(db: Session, user_id: int) -> bool:
    db_user = get_user_by_id(db, user_id)
    if not db_user:
        return False
    db.delete(db_user)
    db.commit()
    return True


def get_user_by_name(db: Session, name):
    if not isinstance(name, str):
        return None
    return db.query(User).filter(User.username.ilike(f"%{name.strip()}%")).first()

# --- NEW: Function to get all leads for web UI ---
def get_all_leads(db: Session):
    return db.query(models.Lead).order_by(models.Lead.created_at.desc()).all()

# --- NEW: Function to get a single lead by its ID ---
def get_lead_by_id(db: Session, lead_id: int):
    return db.query(models.Lead).filter(models.Lead.id == lead_id).first()


# :mag: Get lead by company (case-insensitive, partial match)
def get_lead_by_company(db: Session, company_name: str):
    return db.query(models.Lead).filter(
        func.lower(models.Lead.company_name).like(f"%{company_name.strip().lower()}%")
    ).first()

# --- THIS FUNCTION HAS BEEN CORRECTED ---
def get_tasks_by_username(db: Session, username: str):
    """
    Fetches a unified list of all events (Meetings) and demos for a user.
    This version explicitly names all columns in the subqueries to prevent AttributeError.
    """
    user = get_user_by_username(db, username)
    if not user:
        return []

    meetings_query = (
        db.query(
            Event.id.label("id"),
            Event.lead_id.label("lead_id"),
            Event.event_type.label("event_type"),
            Event.event_time.label("event_time"),
            Event.remark.label("remark")
        ).filter(Event.assigned_to == user.username)
    )

    demos_query = (
        db.query(
            Demo.id.label("id"),
            Demo.lead_id.label("lead_id"),
            literal_column("'Demo'").label("event_type"),
            Demo.start_time.label("event_time"),
            Demo.remark.label("remark")
        ).filter(Demo.assigned_to == user.usernumber)
    )

    all_tasks_cte = union_all(meetings_query, demos_query).cte("all_tasks")

    results = (
        db.query(
            all_tasks_cte,
            Lead.company_name
        )
        .outerjoin(Lead, all_tasks_cte.c.lead_id == Lead.id)
        .order_by(all_tasks_cte.c.event_time.desc())
        .all()
    )

    return results

def get_activities_by_lead_id(db: Session, lead_id: int):
    return db.query(ActivityLog)\
             .filter(ActivityLog.lead_id == lead_id)\
             .order_by(ActivityLog.created_at.desc())\
             .all()

# --- NEW FUNCTION: To fetch and combine all history for a lead ---
def get_lead_history(db: Session, lead_id: int) -> list[schemas.HistoryItemOut]:
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        return []

    history = []

    creator = get_user_by_phone(db, lead.created_by) or get_user_by_name(db, lead.created_by)
    creator_name = creator.username if creator else lead.created_by
    history.append(schemas.HistoryItemOut(
        timestamp=lead.created_at,
        event_type="Lead Creation",
        details=f"Lead created and assigned to {lead.assigned_to}.",
        user=creator_name
    ))

    activities = db.query(ActivityLog).filter(ActivityLog.lead_id == lead_id).all()
    for activity in activities:
        user_match = re.search(r"by (.+?)(?:\.|$)", activity.details)
        user = user_match.group(1).strip() if user_match else "System"
        
        history.append(schemas.HistoryItemOut(
            timestamp=activity.created_at,
            event_type="Activity / Status Change",
            details=activity.details,
            user=user
        ))

    assignments = db.query(AssignmentLog).filter(AssignmentLog.lead_id == lead_id).all()
    for assign in assignments:
        assigner = get_user_by_phone(db, assign.assigned_by) or get_user_by_name(db, assign.assigned_by)
        assigner_name = assigner.username if assigner else assign.assigned_by
        history.append(schemas.HistoryItemOut(
            timestamp=assign.assigned_at,
            event_type="Reassignment",
            details=f"Lead reassigned to {assign.assigned_to}.",
            user=assigner_name
        ))

    history.sort(key=lambda item: item.timestamp, reverse=True)

    return history


def save_lead(
    db: Session,
    lead: schemas.LeadCreate,
    created_by: str,
    assigned_name: str = None,
    assigned_number: str = None
):
    assigned_user = None
    if assigned_name:
        assigned_user = get_user_by_name(db, assigned_name)
    if not assigned_user and assigned_number:
        assigned_user = get_user_by_phone(db, assigned_number)
    
    # If still no user, we check by username directly from the lead data
    if not assigned_user and lead.assigned_to:
        assigned_user = get_user_by_name(db, lead.assigned_to)

    if not assigned_user:
        raise ValueError(
            f"Assigned user not found by name '{assigned_name or lead.assigned_to}' or number '{assigned_number}'"
        )

    db_lead = models.Lead(
        company_name=lead.company_name,
        contact_name=lead.contact_name,
        phone=lead.phone,
        email=lead.email,
        address=lead.address,
        team_size=str(lead.team_size),
        source=lead.source,
        segment=lead.segment,
        remark=lead.remark,
        created_by=created_by,
        assigned_to=assigned_user.username,
        lead_type=lead.lead_type,
        phone_2=lead.phone_2,
        turnover=lead.turnover,
        current_system=lead.current_system,
        machine_specification=lead.machine_specification,
        challenges=lead.challenges,
        created_at=datetime.now()
    )
    db.add(db_lead)
    db.commit()
    db.refresh(db_lead)
    return db_lead

# --- NEW: CRUD function to update a lead's details from the web UI ---
def update_lead(db: Session, lead_id: int, lead_data: schemas.LeadUpdateWeb) -> Optional[models.Lead]:
    db_lead = get_lead_by_id(db, lead_id)
    if not db_lead:
        return None

    update_data = lead_data.model_dump(exclude_unset=True)
    
    updated_by = update_data.pop("updated_by", "System") # Assume a default updater
    
    for key, value in update_data.items():
        if hasattr(db_lead, key):
            setattr(db_lead, key, value)

    # Log this update as an activity
    activity_details = f"Lead details updated via web interface by {updated_by}."
    create_activity_log(db, activity=schemas.ActivityLogCreate(lead_id=lead_id, phase=db_lead.status, details=activity_details))

    db.commit()
    db.refresh(db_lead)
    return db_lead


def update_lead_status(
    db: Session,
    lead_id: int,
    status: str,
    updated_by: str,
    remark: str = None
):
    lead = db.query(models.Lead).filter(models.Lead.id == lead_id).first()
    if lead:
        old_status = lead.status
        lead.status = status
        
        if remark:
            if lead.remark:
                lead.remark += f"\n--\nStatus Update: {remark}"
            else:
                lead.remark = f"Status Update: {remark}"
                
        activity_details = f"Status changed from '{old_status}' to '{status}' by {updated_by}."
        if remark:
            activity_details += f" Remark: {remark}"
        create_activity_log(db, activity=schemas.ActivityLogCreate(lead_id=lead.id, phase=status, details=activity_details))
        
        db.commit()
        db.refresh(lead)
    return lead

def create_event(db: Session, event: schemas.EventCreate):
    db_event = models.Event(
        lead_id=event.lead_id,
        assigned_to=event.assigned_to,
        event_type=event.event_type,
        event_time=event.event_time,
        event_end_time=event.event_end_time,
        created_by=event.created_by,
        remark=event.remark,
        created_at=datetime.now()
    )
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return db_event

# --- NEW: Function to mark a meeting as complete from web ---
def complete_meeting(db: Session, meeting_id: int, notes: str, updated_by: str) -> Optional[models.Event]:
    event = db.query(models.Event).filter(models.Event.id == meeting_id, models.Event.event_type == "Meeting").first()
    if not event:
        return None
    
    event.phase = "Done"
    event.remark = notes
    
    update_lead_status(db, lead_id=event.lead_id, status="Meeting Done", updated_by=updated_by, remark=notes)
    
    db.commit()
    db.refresh(event)
    return event

# --- NEW: Function to mark a demo as complete from web ---
def complete_demo(db: Session, demo_id: int, notes: str, updated_by: str) -> Optional[models.Demo]:
    demo = db.query(models.Demo).filter(models.Demo.id == demo_id).first()
    if not demo:
        return None
        
    demo.phase = "Done"
    demo.remark = notes
    
    update_lead_status(db, lead_id=demo.lead_id, status="Demo Done", updated_by=updated_by, remark=notes)
    
    db.commit()
    db.refresh(demo)
    return demo


create_lead = save_lead

def create_activity_log(db: Session, activity: schemas.ActivityLogCreate):
    db_activity = models.ActivityLog(
        lead_id=activity.lead_id,
        phase=activity.phase,
        details=activity.details
    )
    db.add(db_activity)
    db.commit()
    db.refresh(db_activity)
    return db_activity 

def create_assignment_log(db: Session, log: schemas.AssignmentLogCreate):
    db_log = models.AssignmentLog(
        lead_id=log.lead_id,
        assigned_to=log.assigned_to,
        assigned_by=log.assigned_by
    )
    db.add(db_log)
    db.commit()
    db.refresh(db_log)
    return db_log

def is_user_available(db: Session, username: str, user_phone: str, start_time: datetime, end_time: datetime, exclude_event_id: int = None, exclude_demo_id: int = None) -> Optional[Union[Event, Demo]]:
    """
    Checks if a user has any conflicting "Scheduled" events or demos in a given time slot.
    Returns the conflicting event/demo object if a conflict is found, otherwise None.
    """
    meeting_conflict_query = db.query(Event).filter(
        Event.assigned_to == username,
        Event.event_time < end_time,
        Event.event_end_time > start_time,
        Event.phase == "Scheduled"
    )
    if exclude_event_id:
        meeting_conflict_query = meeting_conflict_query.filter(Event.id != exclude_event_id)
    
    conflicting_meeting = meeting_conflict_query.first()
    if conflicting_meeting:
        return conflicting_meeting

    demo_conflict_query = db.query(Demo).filter(
        Demo.assigned_to == user_phone,
        Demo.start_time < end_time,
        Demo.event_end_time > start_time,
        Demo.phase == "Scheduled"
    )
    if exclude_demo_id:
        demo_conflict_query = demo_conflict_query.filter(Demo.id != exclude_demo_id)
        
    conflicting_demo = demo_conflict_query.first()
    if conflicting_demo:
        return conflicting_demo

    return None

def create_reminder(db: Session, reminder_data: schemas.ReminderCreate):
    """
    Creates a new reminder in the database.
    """
    new_reminder = models.Reminder(
        lead_id=reminder_data.lead_id,
        user_id=reminder_data.user_id,
        assigned_to=reminder_data.assigned_to,
        remind_time=reminder_data.remind_time,
        message=reminder_data.message,
        status="pending",
        created_at=datetime.utcnow()
    )
    db.add(new_reminder)
    db.commit()
    db.refresh(new_reminder)
    return new_reminder


# --- NEW FUNCTION TO GET SCHEDULED MEETINGS ---
def get_scheduled_meetings(db: Session) -> list[models.Event]:
    """
    Retrieves all events from the database that are of type 'Meeting'
    and have a status of 'Scheduled', ordered by their event time.
    """
    return db.query(models.Event).filter(
        models.Event.event_type == "Meeting",
        models.Event.phase == "Scheduled"
    ).order_by(models.Event.event_time.asc()).all()

# --- NEW FUNCTION TO GET SCHEDULED DEMOS ---
def get_scheduled_demos(db: Session) -> list[models.Demo]:
    """
    Retrieves all demos from the database that have a status of 'Scheduled',
    ordered by their start time.
    """
    return db.query(models.Demo).filter(
        models.Demo.phase == "Scheduled"
    ).order_by(models.Demo.start_time.asc()).all()