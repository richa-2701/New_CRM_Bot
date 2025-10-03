# app/crud.py
from datetime import datetime, date
from typing import Optional, Union, List
from sqlalchemy.orm import Session, aliased, joinedload
import re
from sqlalchemy import func, union_all, literal_column, case, and_ ,or_
from app import models, schemas
from app.schemas import (
    UserCreate, UserPasswordChange, LeadCreate, LeadUpdateWeb, EventCreate,
    UserUpdate, HistoryItemOut, ContactCreate, ActivityLogCreate,
    AssignmentLogCreate, ReminderCreate, ActivityLogUpdate,
    ClientCreate, ConvertLeadToClientPayload, ClientContactCreate,
    ClientUpdate, ClientContactUpdate, LeadAttachmentCreate,
    ConvertToProposalPayload, ProposalSentCreate, ProposalSentContactCreate
)
from app.models import (
    User, Event, ActivityLog, Lead, AssignmentLog, Demo, Contact,
    LeadDripAssignment, SentDripMessageLog, DripSequenceStep,
    Client, ClientContact, LeadAttachment,
    ProposalSent, ProposalSentContact
)
import secrets
import string

def get_master_data_by_category(db: Session, category: str):
    return db.query(models.MasterData).filter(models.MasterData.category == category, models.MasterData.is_active == True).order_by(models.MasterData.value).all()

def create_master_data(db: Session, item: schemas.MasterDataCreate):
    db_item = models.MasterData(**item.model_dump())
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

def delete_master_data(db: Session, item_id: int) -> bool:
    db_item = db.query(models.MasterData).filter(models.MasterData.id == item_id).first()
    if not db_item:
        return False
    db.delete(db_item)
    db.commit()
    return True

def create_user(db: Session, user: UserCreate):
    db_user = models.User(
        username=user.username,
        company_name=user.company_name,
        usernumber=user.usernumber,
        email=user.email,
        department=user.department,
        password=user.password,
        role=user.role
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def get_user_by_id(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()

def get_users(db: Session):
    return db.query(models.User).order_by(models.User.username).all()

def get_user_by_username(db: Session, username: str):
    return db.query(models.User).filter(models.User.username == username).first()

def get_user_by_phone(db: Session, phone: Union[str, int]):
    if not phone:
        return None
    phone_str = str(phone).strip()
    sanitized_phone = ''.join(filter(str.isdigit, phone_str))
    possible_formats = {sanitized_phone}
    if not sanitized_phone.startswith('+'):
        possible_formats.add(f"+{sanitized_phone}")
    if len(sanitized_phone) > 10:
        possible_formats.add(sanitized_phone[-10:])
    return db.query(User).filter(User.usernumber.in_(list(possible_formats))).first()

def verify_user(db: Session, username: str, password: str) -> Optional[models.User]:
    user = get_user_by_username(db, username)
    if user and user.password == password:
        return user
    return None

def change_user_password(db: Session, user_data: schemas.UserPasswordChange) -> Optional[models.User]:
    user_to_update = verify_user(db, user_data.username, user_data.old_password)
    if not user_to_update: return None
    user_to_update.password = user_data.new_password
    db.commit()
    db.refresh(user_to_update)
    return user_to_update

def update_user(db: Session, user_id: int, user_data: schemas.UserUpdate) -> Optional[models.User]:
    db_user = get_user_by_id(db, user_id)
    if not db_user: return None
    update_data = user_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_user, key, value)
    db.commit()
    db.refresh(db_user)
    return db_user

def delete_user(db: Session, user_id: int) -> bool:
    db_user = get_user_by_id(db, user_id)
    if not db_user: return False
    db.delete(db_user)
    db.commit()
    return True

def get_user_by_name(db: Session, name):
    if not isinstance(name, str): return None
    return db.query(User).filter(User.username.ilike(f"%{name.strip()}%")).first()

def get_all_leads(db: Session):
    return db.query(models.Lead).filter(models.Lead.isActive == True, models.Lead.status != models.LeadStatus.PROPOSAL_SENT).order_by(models.Lead.created_at.desc()).all()

def get_deleted_leads(db: Session):
    return db.query(models.Lead).filter(models.Lead.isActive == False).order_by(models.Lead.updated_at.desc()).all()

def get_lead_by_id(db: Session, lead_id: int):
    return db.query(models.Lead).filter(models.Lead.id == lead_id).first()

def get_lead_by_company(db: Session, company_name: str):
    return db.query(models.Lead).filter(
        func.lower(models.Lead.company_name).like(f"%{company_name.strip().lower()}%")
    ).first()

def get_tasks_by_username(db: Session, username: str):
    user = get_user_by_username(db, username)
    if not user: return []
    meetings_query = db.query(Event.id.label("id"), Event.lead_id.label("lead_id"), Event.event_type.label("event_type"), Event.event_time.label("event_time"), Event.remark.label("remark")).filter(Event.assigned_to == user.username)
    demos_query = db.query(Demo.id.label("id"), Demo.lead_id.label("lead_id"), literal_column("'Demo'").label("event_type"), Demo.start_time.label("event_time"), Demo.remark.label("remark")).filter(Demo.assigned_to == user.usernumber)
    all_tasks_cte = union_all(meetings_query, demos_query).cte("all_tasks")
    results = db.query(all_tasks_cte, Lead.company_name).outerjoin(Lead, all_tasks_cte.c.lead_id == Lead.id).order_by(all_tasks_cte.c.event_time.desc()).all()
    return results

def get_activities_by_lead_id(db: Session, lead_id: int):
    return db.query(ActivityLog).filter(ActivityLog.lead_id == lead_id).order_by(ActivityLog.created_at.desc()).all()

def get_lead_history(db: Session, lead_id: int) -> list[schemas.HistoryItemOut]:
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead: return []
    history = []
    creator = get_user_by_phone(db, lead.created_by) or get_user_by_name(db, lead.created_by)
    creator_name = creator.username if creator else lead.created_by
    history.append(schemas.HistoryItemOut(timestamp=lead.created_at, event_type="Lead Creation", details=f"Lead created and assigned to {lead.assigned_to}.", user=creator_name))
    activities = db.query(ActivityLog).filter(ActivityLog.lead_id == lead_id).all()
    for activity in activities:
        user_match = re.search(r"by (.+?)(?:\.|$)", activity.details)
        user = user_match.group(1).strip() if user_match else "System"
        history.append(schemas.HistoryItemOut(timestamp=activity.created_at, event_type="Activity / Status Change", details=activity.details, user=user))
    assignments = db.query(AssignmentLog).filter(AssignmentLog.lead_id == lead_id).all()
    for assign in assignments:
        assigner = get_user_by_phone(db, assign.assigned_by) or get_user_by_name(db, assign.assigned_by)
        assigner_name = assigner.username if assigner else assign.assigned_by
        history.append(schemas.HistoryItemOut(timestamp=assign.assigned_at, event_type="Reassignment", details=f"Lead reassigned to {assign.assigned_to}.", user=assigner_name))
    history.sort(key=lambda item: item.timestamp, reverse=True)
    return history

def save_lead(db: Session, lead_data: schemas.LeadCreate) -> models.Lead:
    assigned_user = get_user_by_name(db, lead_data.assigned_to)
    if not assigned_user:
        raise ValueError(f"Assigned user not found by name '{lead_data.assigned_to}'")

    db_lead = models.Lead(
        company_name=lead_data.company_name,
        source=lead_data.source,
        created_by=lead_data.created_by,
        assigned_to=assigned_user.username,
        email=lead_data.email,
        website=lead_data.website,
        linkedIn=lead_data.linkedIn,
        address=lead_data.address,
        address_2=lead_data.address_2,
        city=lead_data.city,
        state=lead_data.state,
        pincode=lead_data.pincode,
        country=lead_data.country,
        team_size=str(lead_data.team_size) if lead_data.team_size else None,
        segment=lead_data.segment,
        verticles=lead_data.verticles,
        remark=lead_data.remark,
        lead_type=lead_data.lead_type,
        phone_2=lead_data.phone_2,
        turnover=lead_data.turnover,
        current_system=lead_data.current_system,
        machine_specification=lead_data.machine_specification,
        challenges=lead_data.challenges,
        opportunity_business=lead_data.opportunity_business,
        target_closing_date=lead_data.target_closing_date,
        version=lead_data.version,
        database_type=lead_data.database_type,
        amc=lead_data.amc,
        gst=lead_data.gst,
        company_pan=lead_data.company_pan,
        created_at=datetime.now()
    )

    db.add(db_lead)
    db.commit()
    db.refresh(db_lead)

    for contact_pydantic in lead_data.contacts:
        contact_dict = contact_pydantic.model_dump()

        db_contact = models.Contact(
            lead_id=db_lead.id,
            contact_name=contact_dict.get('contact_name'),
            phone=contact_dict.get('phone'),
            email=contact_dict.get('email'),
            designation=contact_dict.get('designation'),
            linkedIn=contact_dict.get('linkedIn'),
            pan=contact_dict.get('pan')
        )
        db.add(db_contact)

    db.commit()
    db.refresh(db_lead)

    return db_lead

def create_contact_for_lead(db: Session, lead_id: int, contact: schemas.ContactCreate) -> models.Contact:
    db_contact = models.Contact(**contact.model_dump(), lead_id=lead_id)
    db.add(db_contact)
    db.commit()
    db.refresh(db_contact)
    return db_contact

def get_contacts_by_lead_id(db: Session, lead_id: int) -> List[models.Contact]:
    return db.query(models.Contact).filter(models.Contact.lead_id == lead_id).all()

def update_lead(db: Session, lead_id: int, lead_data: schemas.LeadUpdateWeb):
    db_lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not db_lead:
        return None

    update_data = lead_data.model_dump(exclude_unset=True)

    contacts_data = update_data.pop("contacts", None)
    new_status = update_data.pop("status", None)
    activity_details = update_data.pop("activity_details", None)
    activity_type = update_data.pop("activity_type", "General")

    for key, value in update_data.items():
        if hasattr(db_lead, key):
            setattr(db_lead, key, value)

    db_lead.updated_at = datetime.utcnow()

    if contacts_data is not None:
        db.query(Contact).filter(Contact.lead_id == lead_id).delete(synchronize_session=False)
        for contact_info in contacts_data:
            new_contact = Contact(
                lead_id=db_lead.id,
                contact_name=contact_info.get("contact_name"),
                phone=contact_info.get("phone"),
                email=contact_info.get("email"),
                designation=contact_info.get("designation"),
                linkedIn=contact_info.get("linkedIn"),
                pan=contact_info.get("pan")
            )
            db.add(new_contact)

    if new_status and new_status != db_lead.status:
        update_lead_status(
            db=db,
            lead_id=lead_id,
            status=new_status,
            updated_by="System",
            remark=activity_details
        )
    elif activity_details:
        create_activity_log(db, schemas.ActivityLogCreate(
            lead_id=lead_id,
            phase=db_lead.status,
            details=activity_details,
            activity_type=activity_type
        ))

    db.commit()
    db.refresh(db_lead)
    return db_lead


def soft_delete_lead(db: Session, lead_id: int) -> Optional[models.Lead]:
    db_lead = get_lead_by_id(db, lead_id)
    if db_lead:
        db_lead.isActive = False
        db_lead.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(db_lead)
    return db_lead

def restore_lead(db: Session, lead_id: int) -> Optional[models.Lead]:
    db_lead = get_lead_by_id(db, lead_id)
    if db_lead:
        db_lead.isActive = True
        db_lead.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(db_lead)
    return db_lead

def update_lead_status(db: Session, lead_id: int, status: str, updated_by: str, remark: str = None):
    lead = db.query(models.Lead).filter(models.Lead.id == lead_id).first()
    if lead:
        old_status = lead.status
        lead.status = status

        activity_details = f"Status changed from '{old_status}' to '{status}' by {updated_by}."

        if remark:
            activity_details += f"\nNote: {remark}"

        create_activity_log(db, schemas.ActivityLogCreate(
            lead_id=lead.id,
            phase=status,
            details=activity_details,
        ))
    return lead

def create_event(db: Session, event: schemas.EventCreate):
    db_event = models.Event(
        lead_id=event.lead_id,
        proposal_id=event.proposal_id,
        assigned_to=event.assigned_to,
        event_type=event.event_type,
        meeting_type=event.meeting_type,
        event_time=event.event_time,
        event_end_time=event.event_end_time,
        created_by=event.created_by,
        remark=event.remark,
        created_at=datetime.now(),
        phase="Scheduled"
    )

    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return db_event

def complete_meeting(db: Session, meeting_id: int, notes: str, updated_by: str) -> Optional[models.Event]:
    event = db.query(models.Event).filter(models.Event.id == meeting_id, models.Event.event_type == "Meeting").first()
    if not event: return None
    event.phase = "Done"
    event.remark = notes
    # Update status based on parent
    if event.lead_id:
        update_lead_status(db, lead_id=event.lead_id, status="Meeting Done", updated_by=updated_by, remark=notes)
    elif event.proposal_id:
        # You may need a function to update proposal status
        pass
    db.commit()
    db.refresh(event)
    return event

def complete_demo(db: Session, demo_id: int, notes: str, updated_by: str) -> Optional[models.Demo]:
    demo = db.query(models.Demo).filter(models.Demo.id == demo_id).first()
    if not demo: return None
    demo.phase = "Done"
    demo.remark = notes
    if demo.lead_id:
        update_lead_status(db, lead_id=demo.lead_id, status="Demo Done", updated_by=updated_by, remark=notes)
    elif demo.proposal_id:
        # You may need a function to update proposal status
        pass
    db.commit()
    db.refresh(demo)
    return demo

def create_activity_log(db: Session, activity: schemas.ActivityLogCreate):
    db_activity = models.ActivityLog(
        lead_id=activity.lead_id,
        phase=activity.phase,
        details=activity.details,
        activity_type=activity.activity_type,
        created_at=datetime.utcnow()
    )
    db.add(db_activity)
    db.commit()
    db.refresh(db_activity)
    return db_activity

def create_assignment_log(db: Session, log: schemas.AssignmentLogCreate):
    db_log = models.AssignmentLog(lead_id=log.lead_id, assigned_to=log.assigned_to, assigned_by=log.assigned_by)
    db.add(db_log)
    db.commit()
    db.refresh(db_log)
    return db_log

def is_user_available(db: Session, username: str, user_phone: str, start_time: datetime, end_time: datetime, exclude_event_id: int = None, exclude_demo_id: int = None) -> Optional[Union[Event, Demo]]:
    meeting_conflict_query = db.query(models.Event).filter(
        models.Event.assigned_to == username,
        models.Event.event_time < end_time,
        models.Event.event_end_time > start_time,
        models.Event.phase.in_(["Scheduled", "Rescheduled"])
    )
    if exclude_event_id:
        meeting_conflict_query = meeting_conflict_query.filter(models.Event.id != exclude_event_id)

    conflicting_meeting = meeting_conflict_query.first()
    if conflicting_meeting:
        return conflicting_meeting

    demo_conflict_query = db.query(models.Demo).filter(
        models.Demo.assigned_to == user_phone,
        models.Demo.start_time < end_time,
        models.Demo.event_end_time > start_time,
        models.Demo.phase.in_(["Scheduled", "Rescheduled"])
    )
    if exclude_demo_id:
        demo_conflict_query = demo_conflict_query.filter(models.Demo.id != exclude_demo_id)

    conflicting_demo = demo_conflict_query.first()
    if conflicting_demo:
        return conflicting_demo

    return None

def create_reminder(db: Session, reminder_data: schemas.ReminderCreate):
    user = get_user_by_id(db, reminder_data.user_id)
    if not user:
        return None

    new_reminder = models.Reminder(
        lead_id=reminder_data.lead_id,
        proposal_id=reminder_data.proposal_id,
        user_id=reminder_data.user_id,
        assigned_to=user.username,
        remind_time=reminder_data.remind_time,
        message=reminder_data.message,
        activity_type=reminder_data.activity_type,
        status="pending",
        created_at=datetime.utcnow(),
        is_hidden_from_activity_log=reminder_data.is_hidden_from_activity_log
    )
    db.add(new_reminder)
    db.commit()
    db.refresh(new_reminder)
    return new_reminder

def get_scheduled_meetings(db: Session) -> list[models.Event]:
    return db.query(models.Event).filter(models.Event.event_type == "Meeting", models.Event.phase == "Scheduled").order_by(models.Event.event_time.asc()).all()

def get_all_meetings(db: Session) -> list[models.Event]:
    return db.query(models.Event).filter(models.Event.event_type == "Meeting").order_by(models.Event.event_time.desc()).all()

def get_scheduled_demos(db: Session) -> list[models.Demo]:
    return db.query(models.Demo).filter(models.Demo.phase == "Scheduled").order_by(models.Demo.start_time.asc()).all()

def get_all_demos(db: Session) -> list[models.Demo]:
    return db.query(models.Demo).order_by(models.Demo.start_time.desc()).all()

def get_message_by_id(db: Session, message_id: int):
    return db.query(models.MessageMaster).filter(models.MessageMaster.id == message_id).first()

def get_all_messages(db: Session):
    return db.query(models.MessageMaster).order_by(models.MessageMaster.message_name).all()

def get_all_admins(db: Session) -> List[models.User]:
    return db.query(models.User).filter(func.lower(models.User.role) == 'admin').all()

def get_all_reportable_users(db: Session) -> List[models.User]:
    return db.query(models.User).filter(func.lower(models.User.role) != 'admin').all()


def generate_unique_code(prefix: str, length: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    random_part = ''.join(secrets.choice(alphabet) for _ in range(length))
    timestamp = datetime.utcnow().strftime("%f")
    return f"{prefix.upper()}{timestamp}{random_part}"

def create_message(db: Session, message: schemas.MessageMasterCreate):
    unique_code = generate_unique_code("MSG")
    
    db_message = models.MessageMaster(
        **message.model_dump(),
        message_code=unique_code
    )
    
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message

def update_message(db: Session, message_id: int, message_data: schemas.MessageMasterUpdate):
    db_message = get_message_by_id(db, message_id)
    if not db_message:
        return None
    for key, value in message_data.model_dump().items():
        setattr(db_message, key, value)
    db.commit()
    db.refresh(db_message)
    return db_message

def delete_message(db: Session, message_id: int):
    db_message = get_message_by_id(db, message_id)
    if not db_message:
        return False
    db.delete(db_message)
    db.commit()
    return True

def get_drip_sequence_by_id(db: Session, drip_id: int):
    return db.query(models.DripSequence).filter(models.DripSequence.id == drip_id).first()

def get_all_drip_sequences(db: Session):
    return db.query(models.DripSequence).order_by(models.DripSequence.drip_name).all()

def create_drip_sequence(db: Session, drip: schemas.DripSequenceCreate):
    unique_code = generate_unique_code("DRIP")
    
    db_drip = models.DripSequence(
        drip_name=drip.drip_name, 
        created_by=drip.created_by,
        drip_code=unique_code
    )
    db.add(db_drip)
    db.flush()

    for step_data in drip.steps:
        db_step = models.DripSequenceStep(
            **step_data.model_dump(),
            drip_sequence_id=db_drip.id
        )
        db.add(db_step)

    db.commit()
    db.refresh(db_drip)
    return db_drip


def update_drip_sequence(db: Session, drip_id: int, drip_data: schemas.DripSequenceCreate):
    db_drip = get_drip_sequence_by_id(db, drip_id)
    if not db_drip:
        return None

    db_drip.drip_name = drip_data.drip_name

    db.query(models.DripSequenceStep).filter(models.DripSequenceStep.drip_sequence_id == drip_id).delete()

    for step_data in drip_data.steps:
        db_step = models.DripSequenceStep(**step_data.model_dump(), drip_sequence_id=drip_id)
        db.add(db_step)

    db.commit()
    db.refresh(db_drip)
    return db_drip

def delete_drip_sequence(db: Session, drip_id: int):
    db_drip = get_drip_sequence_by_id(db, drip_id)
    if not db_drip:
        return False
    db.delete(db_drip)
    db.commit()
    return True


def find_and_complete_reminder(db: Session, lead_id: int, message_like: str) -> bool:
    reminder_to_complete = db.query(models.Reminder).filter(
        models.Reminder.lead_id == lead_id,
        models.Reminder.message.like(f"%{message_like}%"),
        models.Reminder.status == 'pending'
    ).order_by(models.Reminder.remind_time.desc()).first()

    if reminder_to_complete:
        reminder_to_complete.status = 'completed'
        db.commit()
        return True

    return False

def get_pending_reminders(db: Session) -> list[models.Reminder]:
    return db.query(models.Reminder).filter(
        models.Reminder.status == 'pending'
    ).order_by(models.Reminder.remind_time.asc()).all()

def assign_drip_to_lead(db: Session, lead_id: int, drip_sequence_id: int) -> LeadDripAssignment:
    db.query(LeadDripAssignment)\
      .filter(LeadDripAssignment.lead_id == lead_id, LeadDripAssignment.is_active == True)\
      .update({"is_active": False})

    new_assignment = LeadDripAssignment(
        lead_id=lead_id,
        drip_sequence_id=drip_sequence_id,
        start_date=date.today()
    )
    db.add(new_assignment)
    db.commit()
    db.refresh(new_assignment)
    return new_assignment

def get_active_drip_assignments(db: Session) -> List[LeadDripAssignment]:
    return db.query(LeadDripAssignment).filter(LeadDripAssignment.is_active == True).all()

def log_sent_drip_message(db: Session, assignment_id: int, step_id: int):
    log_entry = SentDripMessageLog(assignment_id=assignment_id, step_id=step_id)
    db.add(log_entry)
    db.commit()

def get_sent_step_ids_for_assignment(db: Session, assignment_id: int) -> List[int]:
    sent_steps = db.query(SentDripMessageLog.step_id)\
                   .filter(SentDripMessageLog.assignment_id == assignment_id)\
                   .all()
    return [step_id for (step_id,) in sent_steps]

def complete_scheduled_activity(db: Session, reminder_id: int, notes: str, updated_by: str) -> Optional[models.Reminder]:
    reminder_to_complete = db.query(models.Reminder).filter(
        models.Reminder.id == reminder_id,
        models.Reminder.status.in_(['pending', 'sent'])
    ).first()

    if not reminder_to_complete:
        return None

    reminder_to_complete.status = 'completed'

    activity_details = f"{reminder_to_complete.message}\n---\nOutcome: {notes}"
    
    new_activity_log = models.ActivityLog(
        lead_id=reminder_to_complete.lead_id,
        phase="Discussion Done",
        details=f"{activity_details} - Marked as done by {updated_by}",
        activity_type=reminder_to_complete.activity_type
    )
    db.add(new_activity_log)
    
    db.commit()
    db.refresh(reminder_to_complete)
    
    return reminder_to_complete

def get_all_unified_activities(db: Session, username: str, is_admin: bool) -> List[any]:
    logged_activities_query = db.query(
        ActivityLog.id.label("id"),
        literal_column("'log'").label("type"),
        ActivityLog.lead_id.label("lead_id"),
        Lead.company_name.label("company_name"),
        case(
            (ActivityLog.activity_type != None, ActivityLog.activity_type),
            else_=literal_column("'General'")
        ).label("activity_type"),
        ActivityLog.details.label("details"),
        ActivityLog.phase.label("status"),
        ActivityLog.created_at.label("created_at"),
        literal_column("NULL").label("scheduled_for")
    ).join(Lead, Lead.id == ActivityLog.lead_id)

    scheduled_activities_query = db.query(
        models.Reminder.id.label("id"),
        literal_column("'reminder'").label("type"),
        models.Reminder.lead_id.label("lead_id"),
        Lead.company_name.label("company_name"),
        case(
            (models.Reminder.activity_type != None, models.Reminder.activity_type),
            else_=literal_column("'Follow-up'")
        ).label("activity_type"),
        models.Reminder.message.label("details"),
        models.Reminder.status.label("status"),
        models.Reminder.created_at.label("created_at"),
        models.Reminder.remind_time.label("scheduled_for")
    ).join(Lead, Lead.id == models.Reminder.lead_id) \
    .filter(models.Reminder.is_hidden_from_activity_log == False)

    if not is_admin:
        logged_activities_query = logged_activities_query.filter(Lead.assigned_to == username)
        scheduled_activities_query = scheduled_activities_query.filter(models.Reminder.assigned_to == username)

    unified_query = union_all(logged_activities_query, scheduled_activities_query).alias("unified")
    results = db.query(unified_query).order_by(unified_query.c.created_at.desc()).all()
    return results


def reschedule_meeting(db: Session, meeting_id: int, start_time: datetime, end_time: datetime, updated_by: str) -> Optional[models.Event]:
    event = db.query(models.Event).filter(
        models.Event.id == meeting_id,
        models.Event.phase.in_(["Scheduled", "Rescheduled"])
    ).first()

    if not event:
        return None

    old_time = event.event_time.strftime('%Y-%m-%d %H:%M')
    new_time = start_time.strftime('%Y-%m-%d %H:%M')

    event.event_time = start_time
    event.event_end_time = end_time
    event.phase = "Rescheduled"

    create_activity_log(db, schemas.ActivityLogCreate(
        lead_id=event.lead_id,
        phase="Rescheduled",
        details=f"Meeting rescheduled from {old_time} to {new_time} by {updated_by}."
    ))
    db.commit()
    db.refresh(event)
    return event

def reassign_meeting(db: Session, meeting_id: int, new_assignee: User, updated_by: str) -> Optional[models.Event]:
    event = db.query(models.Event).filter(models.Event.id == meeting_id, models.Event.phase.in_(["Scheduled", "Rescheduled"])).first()
    if not event:
        return None

    old_assignee = event.assigned_to
    event.assigned_to = new_assignee.username

    create_activity_log(db, schemas.ActivityLogCreate(
        lead_id=event.lead_id,
        phase="Reassigned",
        details=f"Meeting reassigned from {old_assignee} to {new_assignee.username} by {updated_by}."
    ))
    db.commit()
    db.refresh(event)
    return event

def cancel_meeting(db: Session, meeting_id: int, reason: str, updated_by: str) -> Optional[models.Event]:
    event = db.query(models.Event).filter(models.Event.id == meeting_id, models.Event.phase.in_(["Scheduled", "Rescheduled"])).first()
    if not event:
        return None

    event.phase = "Canceled"
    event.remark = f"Canceled by {updated_by}. Reason: {reason}"

    create_activity_log(db, schemas.ActivityLogCreate(
        lead_id=event.lead_id,
        phase="Canceled",
        details=f"Meeting canceled by {updated_by}. Reason: {reason}"
    ))
    db.commit()
    db.refresh(event)
    return event

def update_meeting_notes(db: Session, meeting_id: int, notes: str, updated_by: str) -> Optional[models.Event]:
    event = db.query(models.Event).filter(models.Event.id == meeting_id, models.Event.phase == "Done").first()
    if not event:
        return None

    event.remark = notes
    create_activity_log(db, schemas.ActivityLogCreate(
        lead_id=event.lead_id,
        phase="Notes Updated",
        details=f"Meeting notes updated by {updated_by}."
    ))
    db.commit()
    db.refresh(event)
    return event

def reschedule_demo(db: Session, demo_id: int, start_time: datetime, end_time: datetime, updated_by: str) -> Optional[models.Demo]:
    demo = db.query(models.Demo).filter(
        models.Demo.id == demo_id,
        models.Demo.phase.in_(["Scheduled", "Rescheduled"])
    ).first()

    if not demo: return None

    old_time = demo.start_time.strftime('%Y-%m-%d %H:%M')
    new_time = start_time.strftime('%Y-%m-%d %H:%M')

    demo.start_time = start_time
    demo.event_end_time = end_time
    demo.phase = "Rescheduled"

    create_activity_log(db, schemas.ActivityLogCreate(lead_id=demo.lead_id, phase="Rescheduled", details=f"Demo rescheduled from {old_time} to {new_time} by {updated_by}."))
    db.commit()
    db.refresh(demo)
    return demo

def reassign_demo(db: Session, demo_id: int, new_assignee: User, updated_by: str) -> Optional[models.Demo]:
    demo = db.query(models.Demo).filter(models.Demo.id == demo_id, models.Demo.phase.in_(["Scheduled", "Rescheduled"])).first()
    if not demo: return None

    old_assignee_num = demo.assigned_to
    demo.assigned_to = new_assignee.usernumber

    create_activity_log(db, schemas.ActivityLogCreate(lead_id=demo.lead_id, phase="Reassigned", details=f"Demo reassigned from user number {old_assignee_num} to {new_assignee.username} by {updated_by}."))
    db.commit()
    db.refresh(demo)
    return demo

def cancel_demo(db: Session, demo_id: int, reason: str, updated_by: str) -> Optional[models.Demo]:
    demo = db.query(models.Demo).filter(models.Demo.id == demo_id, models.Demo.phase.in_(["Scheduled", "Rescheduled"])).first()
    if not demo: return None

    demo.phase = "Canceled"
    demo.remark = f"Canceled by {updated_by}. Reason: {reason}"

    create_activity_log(db, schemas.ActivityLogCreate(lead_id=demo.lead_id, phase="Canceled", details=f"Demo canceled by {updated_by}. Reason: {reason}"))
    db.commit()
    db.refresh(demo)
    return demo

def update_demo_notes(db: Session, demo_id: int, notes: str, updated_by: str) -> Optional[models.Demo]:
    demo = db.query(models.Demo).filter(models.Demo.id == demo_id, models.Demo.phase == "Done").first()
    if not demo: return None

    demo.remark = notes
    create_activity_log(db, schemas.ActivityLogCreate(lead_id=demo.lead_id, phase="Notes Updated", details=f"Demo notes updated by {updated_by}."))
    db.commit()
    db.refresh(demo)
    return demo

def update_activity_log(db: Session, activity_id: int, activity_data: schemas.ActivityLogUpdate) -> Optional[models.ActivityLog]:
    db_activity = db.query(models.ActivityLog).filter(models.ActivityLog.id == activity_id).first()
    if not db_activity:
        return None

    db_activity.details = activity_data.details
    if activity_data.activity_type:
        db_activity.activity_type = activity_data.activity_type

    db.commit()
    db.refresh(db_activity)
    return db_activity

def delete_activity_log(db: Session, activity_id: int) -> bool:
    db_activity = db.query(models.ActivityLog).filter(models.ActivityLog.id == activity_id).first()
    if not db_activity:
        return False
    db.delete(db_activity)
    db.commit()
    return True

def delete_reminder(db: Session, reminder_id: int) -> bool:
    db_reminder = db.query(models.Reminder).filter(models.Reminder.id == reminder_id, models.Reminder.status == 'pending').first()
    if not db_reminder:
        return False
    db.delete(db_reminder)
    db.commit()
    return True


def get_all_leads_with_last_activity(db: Session):
    latest_activity_subquery = db.query(
        ActivityLog,
        func.row_number().over(
            partition_by=ActivityLog.lead_id,
            order_by=ActivityLog.created_at.desc()
        ).label("row_num")
    ).subquery()

    latest_activity = aliased(ActivityLog, latest_activity_subquery)

    results = db.query(
        Lead,
        latest_activity
    ).outerjoin(
        latest_activity,
        (Lead.id == latest_activity.lead_id) & (latest_activity_subquery.c.row_num == 1)
    ).filter(Lead.isActive == True, Lead.status != models.LeadStatus.PROPOSAL_SENT).order_by(Lead.created_at.desc()).all()

    leads_to_return = []
    for lead, activity in results:
        lead.last_activity = activity
        leads_to_return.append(lead)

    return leads_to_return

def create_client(db: Session, client_data: schemas.ClientCreate) -> models.Client:
    db_client = models.Client(
        company_name=client_data.company_name,
        website=client_data.website,
        linkedIn=client_data.linkedIn,
        company_email=client_data.company_email,
        company_phone_2=client_data.company_phone_2,
        address=client_data.address,
        address_2=client_data.address_2,
        city=client_data.city,
        state=client_data.state,
        pincode=client_data.pincode,
        country=client_data.country,
        segment=client_data.segment,
        verticles=client_data.verticles,
        team_size=str(client_data.team_size) if client_data.team_size else None,
        turnover=client_data.turnover,
        current_system=client_data.current_system,
        machine_specification=client_data.machine_specification,
        challenges=client_data.challenges,
        version=client_data.version,
        database_type=client_data.database_type,
        amc=client_data.amc,
        gst=client_data.gst,
        converted_date=client_data.converted_date or date.today(),
        created_at=datetime.now()
    )
    db.add(db_client)
    db.flush()

    for contact_pydantic in client_data.contacts:
        contact_dict = contact_pydantic.model_dump()
        db_client_contact = models.ClientContact(
            client_id=db_client.id,
            contact_name=contact_dict.get('contact_name'),
            phone=contact_dict.get('phone'),
            email=contact_dict.get('email'),
            designation=contact_dict.get('designation'),
            linkedIn=contact_dict.get('linkedIn'),
            pan=contact_dict.get('pan')
        )
        db.add(db_client_contact)

    db.commit()
    db.refresh(db_client)
    return db_client

def get_all_clients(db: Session) -> List[models.Client]:
    return db.query(models.Client).options(joinedload(models.Client.contacts)).order_by(models.Client.created_at.desc()).all()

def get_client_by_id(db: Session, client_id: int) -> Optional[models.Client]:
    return db.query(models.Client).options(joinedload(models.Client.contacts), joinedload(models.Client.attachments)).filter(models.Client.id == client_id).first()

def update_client(db: Session, client_id: int, client_data: schemas.ClientUpdate) -> Optional[models.Client]:
    db_client = db.query(models.Client).filter(models.Client.id == client_id).first()
    if not db_client:
        return None

    update_data = client_data.model_dump(exclude_unset=True)
    contacts_data = update_data.pop("contacts", None)

    for key, value in update_data.items():
        if hasattr(db_client, key):
            setattr(db_client, key, value)

    db_client.updated_at = datetime.utcnow()

    if contacts_data is not None:
        db.query(models.ClientContact).filter(models.ClientContact.client_id == client_id).delete(synchronize_session=False)
        for contact_info in contacts_data:
            new_contact = models.ClientContact(
                client_id=db_client.id,
                contact_name=contact_info.get("contact_name"),
                phone=contact_info.get("phone"),
                email=contact_info.get("email"),
                designation=contact_info.get("designation"),
                linkedIn=contact_info.get("linkedIn"),
                pan=contact_info.get("pan")
            )
            db.add(new_contact)

    db.commit()
    db.refresh(db_client)
    return db_client


# --- START: FIX ---
def convert_lead_to_client(db: Session, lead_id: int, conversion_data: schemas.ConvertLeadToClientPayload, converted_by: str) -> models.Client:
    lead = db.query(models.Lead).filter(models.Lead.id == lead_id).first()
    if not lead:
        raise ValueError(f"Lead with ID {lead_id} not found.")

    client_contacts_create = []
    for contact_data in conversion_data.contacts:
        client_contacts_create.append(schemas.ClientContactCreate(**contact_data.model_dump()))

    client_create_payload = schemas.ClientCreate(
        company_name=conversion_data.company_name or lead.company_name,
        website=conversion_data.website or lead.website,
        linkedIn=conversion_data.linkedIn or lead.linkedIn,
        company_email=conversion_data.company_email or lead.email,
        company_phone_2=conversion_data.company_phone_2 or lead.phone_2,
        address=conversion_data.address or lead.address,
        address_2=conversion_data.address_2 or lead.address_2,
        city=conversion_data.city or lead.city,
        state=conversion_data.state or lead.state,
        pincode=conversion_data.pincode or lead.pincode,
        country=conversion_data.country or lead.country,
        segment=conversion_data.segment or lead.segment,
        verticles=conversion_data.verticles or lead.verticles,
        team_size=str(conversion_data.team_size) if conversion_data.team_size else str(lead.team_size) if lead.team_size else None,
        turnover=conversion_data.turnover or lead.turnover,
        current_system=conversion_data.current_system or lead.current_system,
        machine_specification=conversion_data.machine_specification or lead.machine_specification,
        challenges=conversion_data.challenges or lead.challenges,
        version=conversion_data.version,
        database_type=conversion_data.database_type,
        amc=conversion_data.amc,
        gst=conversion_data.gst,
        converted_date=conversion_data.converted_date or date.today(),
        contacts=client_contacts_create
    )

    new_client = create_client(db, client_create_payload)

    # Transfer attachments from lead to the new client
    # This assumes you have added a nullable `client_id` to the LeadAttachment model
    # and made `lead_id` nullable.
    db.query(models.LeadAttachment).filter(
        models.LeadAttachment.lead_id == lead.id
    ).update(
        {"client_id": new_client.id, "lead_id": None},
        synchronize_session=False
    )

    update_lead_status(db, lead_id, models.LeadStatus.WON_DEAL_DONE.value, converted_by, remark="Converted to Client")

    db.commit() # Commit the attachment updates and lead status change
    db.refresh(lead)
    db.refresh(new_client)
    return new_client
# --- END: FIX ---


def generate_user_performance_data(db: Session, user_id: int, start_date: date, end_date: date):
    user = get_user_by_id(db, user_id)
    if not user:
        return None

    start_datetime = datetime.combine(start_date, datetime.min.time())
    end_datetime = datetime.combine(end_date, datetime.max.time())

    new_leads_assigned = db.query(models.Lead).filter(
        models.Lead.assigned_to == user.username,
        models.Lead.created_at.between(start_datetime, end_datetime)
    ).count()

    meetings_scheduled = db.query(models.Event).filter(
        models.Event.assigned_to == user.username,
        models.Event.event_type == 'Meeting',
        models.Event.created_at.between(start_datetime, end_datetime)
    ).count()

    demos_scheduled = db.query(models.Demo).filter(
        models.Demo.assigned_to == user.usernumber,
        models.Demo.created_at.between(start_datetime, end_datetime)
    ).count()

    meetings_completed = db.query(models.Event).filter(
        models.Event.assigned_to == user.username,
        models.Event.phase == 'Done',
        models.Event.event_time.between(start_datetime, end_datetime)
    ).count()

    demos_completed = db.query(models.Demo).filter(
        models.Demo.assigned_to == user.usernumber,
        models.Demo.phase == 'Done',
        models.Demo.start_time.between(start_datetime, end_datetime)
    ).count()

    activities_logged = db.query(models.ActivityLog).join(models.Lead).filter(
        models.Lead.assigned_to == user.username,
        models.ActivityLog.created_at.between(start_datetime, end_datetime)
    ).count()

    won_logs = db.query(models.ActivityLog).join(models.Lead).filter(
        models.Lead.assigned_to == user.username,
        models.ActivityLog.details.like(f"%Status changed from%to '{models.LeadStatus.WON_DEAL_DONE.value}'%"),
        models.ActivityLog.created_at.between(start_datetime, end_datetime)
    ).all()
    deals_won_count = len(won_logs)

    lost_logs = db.query(models.ActivityLog).join(models.Lead).filter(
        models.Lead.assigned_to == user.username,
        models.ActivityLog.details.like(f"%Status changed from%to '{models.LeadStatus.LOST.value}'%"),
        models.ActivityLog.created_at.between(start_datetime, end_datetime)
    ).count()
    
    conversion_rate = (deals_won_count / new_leads_assigned * 100) if new_leads_assigned > 0 else 0

    activity_volume_data = [
        {"name": "Meetings Scheduled", "value": meetings_scheduled},
        {"name": "Demos Scheduled", "value": demos_scheduled},
        {"name": "Meetings Completed", "value": meetings_completed},
        {"name": "Demos Completed", "value": demos_completed},
        {"name": "Activities Logged", "value": activities_logged},
    ]

    leads_in_progress = db.query(models.Lead).filter(
        models.Lead.assigned_to == user.username,
        models.Lead.status.notin_([models.LeadStatus.WON_DEAL_DONE.value, models.LeadStatus.LOST.value]),
        models.Lead.created_at.between(start_datetime, end_datetime)
    ).count()

    lead_outcome_data = [
        {"name": "Deals Won", "value": deals_won_count},
        {"name": "Leads Lost", "value": lost_logs},
        {"name": "In Progress", "value": leads_in_progress},
    ]

    deals_won_table_data = []
    for log in won_logs:
        lead = log.lead
        time_to_close = (log.created_at.date() - lead.created_at.date()).days
        deals_won_table_data.append({
            "client_name": lead.company_name,
            "converted_date": log.created_at.date(),
            "source": lead.source,
            "time_to_close": time_to_close
        })

    return {
        "kpi_summary": {
            "new_leads_assigned": new_leads_assigned,
            "meetings_scheduled": meetings_scheduled,
            "demos_scheduled": demos_scheduled,
            "meetings_completed": meetings_completed,
            "demos_completed": demos_completed,
            "activities_logged": activities_logged,
            "deals_won": deals_won_count,
            "leads_lost": lost_logs,
            "conversion_rate": round(conversion_rate, 1)
        },
        "visualizations": {
            "activity_volume": activity_volume_data,
            "lead_outcome": lead_outcome_data
        },
        "tables": {
            "deals_won": deals_won_table_data
        }
    }

def add_lead_attachment(db: Session, lead_id: int, attachment_data: schemas.LeadAttachmentCreate) -> models.LeadAttachment:
    db_attachment = models.LeadAttachment(
        lead_id=lead_id,
        **attachment_data.model_dump()
    )
    db.add(db_attachment)
    db.commit()
    db.refresh(db_attachment)
    return db_attachment

def delete_lead_attachment(db: Session, attachment_id: int) -> bool:
    db_attachment = db.query(models.LeadAttachment).filter(models.LeadAttachment.id == attachment_id).first()
    if not db_attachment:
        return False
    db.delete(db_attachment)
    db.commit()
    return True

def get_all_proposals(db: Session) -> List[models.ProposalSent]:
    """Fetches all proposals from the database."""
    return db.query(models.ProposalSent).order_by(models.ProposalSent.converted_at.desc()).all()

# --- START: FIX ---
def convert_lead_to_proposal(db: Session, lead_id: int, payload: schemas.ConvertToProposalPayload, converted_by: str) -> models.ProposalSent:
    """Converts a lead to the 'Proposal Sent' stage, creating new records safely."""
    lead = db.query(models.Lead).filter(models.Lead.id == lead_id).first()
    if not lead:
        raise ValueError(f"Lead with ID {lead_id} not found.")
    if lead.status == models.LeadStatus.PROPOSAL_SENT.value:
        raise ValueError(f"Lead {lead_id} has already been converted.")

    proposal_base_data = {
        'company_name': lead.company_name, 'email': lead.email, 'website': lead.website,
        'linkedIn': lead.linkedIn, 'address': lead.address, 'address_2': lead.address_2,
        'city': lead.city, 'state': lead.state, 'pincode': lead.pincode, 'country': lead.country,
        'source': lead.source, 'segment': lead.segment, 'team_size': lead.team_size,
        'remark': lead.remark, 'assigned_to': lead.assigned_to, 'created_by': lead.created_by,
        'phone_2': lead.phone_2, 'turnover': lead.turnover, 'current_system': lead.current_system,
        'machine_specification': lead.machine_specification, 'challenges': lead.challenges,
        'lead_type': lead.lead_type, 'opportunity_business': lead.opportunity_business,
        'target_closing_date': lead.target_closing_date, 'version': lead.version,
        'database_type': lead.database_type, 'amc': lead.amc, 'gst': lead.gst,
        'company_pan': lead.company_pan
    }

    update_data = payload.model_dump(exclude_unset=True)
    proposal_contacts_data = update_data.pop('contacts', [])
    final_proposal_data = {**proposal_base_data, **update_data}

    final_proposal_data['original_lead_id'] = lead.id
    final_proposal_data['converted_at'] = datetime.utcnow()
    final_proposal_data['status'] = models.LeadStatus.PROPOSAL_SENT.value

    # Safely remove the 'isActive' key if it exists before creating the model instance
    final_proposal_data.pop('isActive', None)

    new_proposal = models.ProposalSent(**final_proposal_data)
    db.add(new_proposal)
    db.flush()

    for contact_data in proposal_contacts_data:
        db_contact = models.ProposalSentContact(
            proposal_id=new_proposal.id,
            **contact_data
        )
        db.add(db_contact)

    db.query(models.Event).filter(
        models.Event.lead_id == lead.id,
        models.Event.phase.in_(['Scheduled', 'Rescheduled'])
    ).update({'lead_id': None, 'proposal_id': new_proposal.id}, synchronize_session=False)

    db.query(models.Demo).filter(
        models.Demo.lead_id == lead.id,
        models.Demo.phase.in_(['Scheduled', 'Rescheduled'])
    ).update({'lead_id': None, 'proposal_id': new_proposal.id}, synchronize_session=False)
    
    db.query(models.Reminder).filter(
        models.Reminder.lead_id == lead.id,
        models.Reminder.status == 'pending'
    ).update({'lead_id': None, 'proposal_id': new_proposal.id}, synchronize_session=False)

    update_lead_status(db, lead.id, models.LeadStatus.PROPOSAL_SENT.value, converted_by, remark="Converted to Proposal")

    db.commit()
    db.refresh(new_proposal)
    return new_proposal
# --- END: FIX ---