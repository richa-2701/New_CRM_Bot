# app/models.py
import enum
from datetime import datetime, date
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean, Date
from sqlalchemy.orm import relationship
from app.db import Base


class MasterData(Base):
    __tablename__ = "MasterData"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    category = Column(String(100), nullable=False, index=True)
    value = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class LeadStatus(str, enum.Enum):
    NEW = "new"
    QUALIFIED = "qualified"
    UNQUALIFIED = "unqualified"
    NOT_OUR_SEGMENT = "not_our_segment"
    MEETING_SCHEDULED = "Meeting Scheduled"
    DEMO_SCHEDULED = "Demo Scheduled"
    MEETING_DONE = "Meeting Done"
    DEMO_DONE = "Demo Done"
    PROPOSAL_SENT = "Proposal Sent"
    WON_DEAL_DONE = "Won/Deal Done"
    LOST = "Lost"

class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(100), nullable=False)
    company_name = Column(String(100), nullable=False, index=True)
    usernumber = Column(String(15), unique=True, nullable=False)
    email = Column("Email", String(100), nullable=True)
    department = Column(String(100), nullable=True)
    password = Column("Password", String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    role = Column(String(50), nullable=False, default="Company User")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    leads = relationship("Lead", back_populates="assigned_to_user")
    reminders = relationship("Reminder", back_populates="user")
    task_history = relationship("TaskHistory", back_populates="user")

class Contact(Base):
    __tablename__ = "contacts"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False)
    contact_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    designation = Column(String, nullable=True)
    linkedIn = Column(String, nullable=True)
    pan = Column(String, nullable=True)
    lead = relationship("Lead", back_populates="contacts")

class Lead(Base):
    __tablename__ = "leads"
    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String, nullable=False)
    source = Column(String, nullable=False)
    created_by = Column(String, nullable=False)
    assigned_to = Column(String, ForeignKey("users.username"), nullable=False)
    email = Column(String, nullable=True)
    website = Column(String, nullable=True)
    linkedIn = Column(String, nullable=True)
    address = Column(String, nullable=True)
    address_2 = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    pincode = Column(String, nullable=True)
    country = Column(String, nullable=True)
    segment = Column(String, nullable=True)
    verticles = Column(String, nullable=True)
    team_size = Column(String, nullable=True)
    remark = Column(Text, nullable=True)
    status = Column(String, default="new")
    lead_type = Column(String, nullable=True)
    phone_2 = Column(String, nullable=True)
    turnover = Column(String, nullable=True)
    current_system = Column(String, nullable=True)
    machine_specification = Column(Text, nullable=True)
    challenges = Column(Text, nullable=True)
    opportunity_business = Column(String, nullable=True)
    target_closing_date = Column(Date, nullable=True)
    version = Column(String, nullable=True)
    database_type = Column(String, nullable=True)
    amc = Column(String, nullable=True)
    gst = Column(String, nullable=True)
    company_pan = Column(String, nullable=True)
    isActive = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    contacts = relationship("Contact", back_populates="lead", cascade="all, delete-orphan")
    assigned_to_user = relationship("User", back_populates="leads")
    reminders = relationship("Reminder", foreign_keys='Reminder.lead_id', back_populates="lead")
    events = relationship("Event", foreign_keys='Event.lead_id', back_populates="lead")
    demos = relationship("Demo", foreign_keys='Demo.lead_id', back_populates="lead")
    activities = relationship("ActivityLog", back_populates="lead")
    attachments = relationship("LeadAttachment", back_populates="lead", cascade="all, delete-orphan")
    task_history = relationship("TaskHistory", back_populates="lead")
    AssignmentLogs = relationship("AssignmentLog", back_populates="lead")
    drip_assignments = relationship("LeadDripAssignment", back_populates="lead")
    tasks = relationship("Task", back_populates="lead")
    meetings = relationship("Meeting", back_populates="lead")
    feedbacks = relationship("Feedback", back_populates="lead")

class LeadAttachment(Base):
    __tablename__ = "lead_attachments"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    file_path = Column(String, nullable=False)
    original_file_name = Column(String, nullable=False)
    uploaded_by = Column(String, nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    lead = relationship("Lead", back_populates="attachments")
    client = relationship("Client", back_populates="attachments")
    
class ActivityLog(Base):
    __tablename__ = "activity_logs"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False)
    activity_type = Column(String, nullable=False, default="Call")
    phase = Column(String, nullable=False)
    details = Column(Text, nullable=False)
    attachment_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    lead = relationship("Lead", back_populates="activities")

class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True)
    proposal_id = Column(Integer, ForeignKey("proposal_sent.id"), nullable=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    assigned_to = Column(String)
    event_type = Column(String)
    meeting_type = Column(String, nullable=True)
    event_time = Column(DateTime)
    event_end_time = Column(DateTime, nullable=True)
    created_by = Column(String)
    remark = Column(String)
    phase = Column(String, default="Scheduled")
    created_at = Column(DateTime, default=datetime.utcnow)
    lead = relationship("Lead", back_populates="events")

class Reminder(Base):
    __tablename__ = "reminders"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True)
    proposal_id = Column(Integer, ForeignKey("proposal_sent.id"), nullable=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    remind_time = Column(DateTime)
    activity_type = Column(String, default="Follow-up")
    message = Column(String)
    assigned_to = Column(String)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    is_hidden_from_activity_log = Column(Boolean, default=False)
    user = relationship("User", back_populates="reminders")
    lead = relationship("Lead", back_populates="reminders")

class Demo(Base):
    __tablename__ = "demos"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True)
    proposal_id = Column(Integer, ForeignKey("proposal_sent.id"), nullable=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    scheduled_by = Column(String)
    assigned_to = Column(String)
    start_time = Column(DateTime)
    event_end_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    phase = Column(String, default="Scheduled")
    remark = Column(Text, nullable=True)
    lead = relationship("Lead", back_populates="demos")

class ProposalSent(Base):
    __tablename__ = "proposal_sent"
    id = Column(Integer, primary_key=True, index=True)
    original_lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False)
    company_name = Column(String, nullable=False)
    source = Column(String, nullable=False)
    created_by = Column(String, nullable=False)
    assigned_to = Column(String, nullable=False)
    email = Column(String, nullable=True)
    website = Column(String, nullable=True)
    linkedIn = Column(String, nullable=True)
    address = Column(Text, nullable=True)
    address_2 = Column(Text, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    pincode = Column(String, nullable=True)
    country = Column(String, nullable=True)
    segment = Column(String, nullable=True)
    verticles = Column(String, nullable=True)
    team_size = Column(String, nullable=True)
    remark = Column(Text, nullable=True)
    status = Column(String, default="Proposal Sent")
    lead_type = Column(String, nullable=True)
    phone_2 = Column(String, nullable=True)
    turnover = Column(String, nullable=True)
    current_system = Column(String, nullable=True)
    machine_specification = Column(Text, nullable=True)
    challenges = Column(Text, nullable=True)
    opportunity_business = Column(String, nullable=True)
    target_closing_date = Column(Date, nullable=True)
    version = Column(String, nullable=True)
    database_type = Column(String, nullable=True)
    amc = Column(String, nullable=True)
    gst = Column(String, nullable=False)
    company_pan = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    converted_at = Column(DateTime, default=datetime.utcnow)

    contacts = relationship("ProposalSentContact", back_populates="proposal", cascade="all, delete-orphan")
    activities = relationship("ProposalSentActivityLog", back_populates="proposal", cascade="all, delete-orphan")
    reminders = relationship("Reminder", foreign_keys=[Reminder.proposal_id])
    events = relationship("Event", foreign_keys=[Event.proposal_id])
    demos = relationship("Demo", foreign_keys=[Demo.proposal_id])

class ProposalSentContact(Base):
    __tablename__ = "proposal_sent_contacts"
    id = Column(Integer, primary_key=True, index=True)
    proposal_id = Column(Integer, ForeignKey("proposal_sent.id"), nullable=False)
    contact_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    designation = Column(String, nullable=True)
    linkedIn = Column(String, nullable=True)
    pan = Column(String, nullable=True)
    proposal = relationship("ProposalSent", back_populates="contacts")

class ProposalSentActivityLog(Base):
    __tablename__ = "proposal_sent_activity_logs"
    id = Column(Integer, primary_key=True, index=True)
    proposal_id = Column(Integer, ForeignKey("proposal_sent.id"), nullable=False)
    activity_type = Column(String, nullable=False, default="Call")
    phase = Column(String, nullable=False)
    details = Column(Text, nullable=False)
    attachment_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    proposal = relationship("ProposalSent", back_populates="activities")

class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    task_type = Column(String)
    date_time = Column(DateTime)
    assigned_to = Column(String)
    remark = Column(String)
    status = Column(String, default="pending")
    lead = relationship("Lead", back_populates="tasks")

class TaskHistory(Base):
    __tablename__ = "task_history"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    action = Column(String)
    details = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
    lead = relationship("Lead", back_populates="task_history")
    user = relationship("User", back_populates="task_history")

class Meeting(Base):
    __tablename__ = "meetings"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    scheduled_by = Column(String)
    assigned_to = Column(String)
    start_time = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    lead = relationship("Lead", back_populates="meetings")

class Feedback(Base):
    __tablename__ = "feedbacks"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    feedback_by = Column(String)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    lead = relationship("Lead", back_populates="feedbacks")

class AssignmentLog(Base):
    __tablename__ = "AssignmentLogs"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    assigned_to = Column(String)
    assigned_by = Column(String)
    assigned_at = Column(DateTime, default=datetime.utcnow)
    lead = relationship("Lead", back_populates="AssignmentLogs")

class MessageMaster(Base):
    __tablename__ = "MessageMaster"
    id = Column(Integer, primary_key=True, index=True)
    message_code = Column(String, unique=True, nullable=False, server_default="DEFAULT_CODE")
    message_name = Column(String, nullable=False)
    message_content = Column(Text, nullable=True)
    message_type = Column(String, nullable=False)
    attachment_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String, nullable=False)

class DripSequence(Base):
    __tablename__ = "DripSequence"
    id = Column(Integer, primary_key=True, index=True)
    drip_code = Column(String, unique=True, nullable=False, server_default="DEFAULT_CODE")
    drip_name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String, nullable=False)
    steps = relationship("DripSequenceStep", back_populates="drip_sequence", cascade="all, delete-orphan")
    lead_assignments = relationship("LeadDripAssignment", back_populates="drip_sequence")

class DripSequenceStep(Base):
    __tablename__ = "DripSequenceStep"
    id = Column(Integer, primary_key=True, index=True)
    drip_sequence_id = Column(Integer, ForeignKey("DripSequence.id"), nullable=False)
    message_id = Column(Integer, ForeignKey("MessageMaster.id"), nullable=False)
    day_to_send = Column(Integer, nullable=False)
    time_to_send = Column(String, nullable=False)
    sequence_order = Column(Integer, nullable=False)
    drip_sequence = relationship("DripSequence", back_populates="steps")
    message = relationship("MessageMaster")

class LeadDripAssignment(Base):
    __tablename__ = "LeadDripAssignment"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False)
    drip_sequence_id = Column(Integer, ForeignKey("DripSequence.id"), nullable=False)
    start_date = Column(Date, nullable=False, default=date.today)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    lead = relationship("Lead", back_populates="drip_assignments")
    drip_sequence = relationship("DripSequence", back_populates="lead_assignments")
    sent_messages = relationship("SentDripMessageLog", back_populates="assignment", cascade="all, delete-orphan")

class SentDripMessageLog(Base):
    __tablename__ = "SentDripMessageLog"
    id = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(Integer, ForeignKey("LeadDripAssignment.id"), nullable=False)
    step_id = Column(Integer, ForeignKey("DripSequenceStep.id"), nullable=False)
    sent_at = Column(DateTime, default=datetime.utcnow)
    assignment = relationship("LeadDripAssignment", back_populates="sent_messages")
    step = relationship("DripSequenceStep")

class Client(Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_name = Column(String, nullable=False)
    website = Column(String, nullable=True)
    linkedIn = Column(String, nullable=True)
    company_email = Column(String, nullable=True)
    company_phone_2 = Column(String, nullable=True)
    address = Column(String, nullable=True)
    address_2 = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    pincode = Column(String, nullable=True)
    country = Column(String, nullable=True)
    segment = Column(String, nullable=True)
    verticles = Column(String, nullable=True)
    team_size = Column(String, nullable=True)
    turnover = Column(String, nullable=True)
    current_system = Column(String, nullable=True)
    machine_specification = Column(Text, nullable=True)
    challenges = Column(Text, nullable=True)
    version = Column(String, nullable=True)
    database_type = Column(String, nullable=True)
    amc = Column(String, nullable=True)
    gst = Column(String, nullable=True)
    converted_date = Column(Date, nullable=False, default=date.today)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    contacts = relationship("ClientContact", back_populates="client", cascade="all, delete-orphan")
    events = relationship("Event", foreign_keys=[Event.client_id])
    demos = relationship("Demo", foreign_keys=[Demo.client_id])
    reminders = relationship("Reminder", foreign_keys=[Reminder.client_id])
    attachments = relationship("LeadAttachment", back_populates="client")

class ClientContact(Base):
    __tablename__ = "client_contacts"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    contact_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    designation = Column(String, nullable=True)
    linkedIn = Column(String, nullable=True)
    pan = Column(String, nullable=True)
    client = relationship("Client", back_populates="contacts")