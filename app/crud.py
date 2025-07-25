# app/crud.py
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
from app import models, schemas
from app.models import User, Event, ActivityLog, Lead, AssignmentLog
import re

def create_user(db: Session, user: schemas.UserCreate):
    db_user = models.User(
        username=user.username,
        usernumber=user.usernumber,
        email=user.email,
        department=user.department,
        password=user.password  
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def get_user_by_username(db: Session, username: str):
    return db.query(models.User).filter(models.User.username == username).first()


def get_user_by_phone(db: Session, phone: str):
    return db.query(User).filter(User.usernumber == phone.strip()).first()
# :mag: Get user by name (username - case-insensitive)

def verify_user(db: Session, username: str, password: str):
    user = get_user_by_username(db, username)
    if user and user.password == password:
        return user
    return None


def get_user_by_name(db: Session, name):
    if not isinstance(name, str):
        return None
    return db.query(User).filter(User.username.ilike(f"%{name.strip()}%")).first()

# :mag: Get lead by company (case-insensitive, partial match)
def get_lead_by_company(db: Session, company_name: str):
    return db.query(models.Lead).filter(
        func.lower(models.Lead.company_name).like(f"%{company_name.strip().lower()}%")
    ).first()

def get_tasks_by_username(db: Session, username: str):
    """
    Fetches all events (tasks) for a user and joins with the leads table
    to get the company name.
    """
    return (
        db.query(Event, Lead.company_name)
        .join(Lead, Event.lead_id == Lead.id)
        .filter(Event.assigned_to == username)
        .order_by(Event.event_time)
        .all()
    )

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

    # 1. Lead Creation
    creator = get_user_by_phone(db, lead.created_by) or get_user_by_name(db, lead.created_by)
    creator_name = creator.username if creator else lead.created_by
    history.append(schemas.HistoryItemOut(
        timestamp=lead.created_at,
        event_type="Lead Creation",
        details=f"Lead created and assigned to {lead.assigned_to}.",
        user=creator_name
    ))

    # 2. All Activities (including status changes)
    activities = db.query(ActivityLog).filter(ActivityLog.lead_id == lead_id).all()
    for activity in activities:
        # We need to figure out who performed the action from the details string
        user_match = re.search(r"by (.+?)(?:\.|$)", activity.details)
        user = user_match.group(1).strip() if user_match else "System"
        
        history.append(schemas.HistoryItemOut(
            timestamp=activity.created_at,
            event_type="Activity / Status Change",
            details=activity.details,
            user=user
        ))

    # 3. Reassignments
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

    # Sort the entire history chronologically
    history.sort(key=lambda item: item.timestamp, reverse=True)

    return history


# :floppy_disk: Create a new lead - checks assigned_to by name or number
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
    if not assigned_user:
        raise ValueError(
            f"Assigned user not found by name '{assigned_name}' or number '{assigned_number}'"
        )
    db_lead = models.Lead(
        company_name=lead.company_name,
        contact_name=lead.contact_name,
        phone=lead.phone,
        email=lead.email,
        address=lead.address,
        team_size=lead.team_size,
        source=lead.source,
        segment=lead.segment,
        remark=lead.remark,
        created_by=created_by,
        assigned_to=assigned_user.username,
        phone_2=lead.phone_2,
        turnover=lead.turnover,
        current_system=lead.current_system,
        machine_specification=lead.machine_specification,
        challenges=lead.challenges,
        created_at=datetime.utcnow()
    )
    db.add(db_lead)
    db.commit()
    db.refresh(db_lead)
    # This automatically logs the "New Lead" activity now.
    return db_lead

# :arrows_counterclockwise: Update lead status and add activity log
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

# :date: Create a new event (Meeting or Demo)
def create_event(db: Session, event: schemas.EventCreate):
    db_event = models.Event(
        lead_id=event.lead_id,
        assigned_to=event.assigned_to,
        event_type=event.event_type,
        event_time=event.event_time,
        created_by=event.created_by,
        remark=event.remark,
        created_at=datetime.utcnow()
    )
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return db_event
# :pushpin: Alias
create_lead = save_lead

# --- CRUD FUNCTION FOR ACTIVITY LOG ---
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

# --- CRUD FUNCTION FOR ASSIGNMENT LOG ---
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