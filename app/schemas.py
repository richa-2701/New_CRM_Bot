# app/schemas.py
from pydantic import BaseModel, ConfigDict
from typing import Optional, Union, List
from datetime import datetime, time, date

# --- MasterData SCHEMAS ---
class MasterDataBase(BaseModel):
    category: str
    value: str

class MasterDataCreate(MasterDataBase):
    pass

class MasterDataOut(MasterDataBase):
    id: int
    is_active: bool
    class Config:
        from_attributes = True

# ---------------- CONTACT SCHEMAS ----------------
class ContactBase(BaseModel):
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    designation: Optional[str] = None
    linkedIn: Optional[str] = None # New Field
    pan: Optional[str] = None # New Field

class ContactCreate(ContactBase):
    pass

class ContactUpdate(ContactBase):
    id: Optional[int] = None

class ContactOut(ContactBase):
    id: int
    lead_id: int
    model_config = ConfigDict(from_attributes=True)

# NEW CLIENT CONTACT SCHEMAS
class ClientContactBase(BaseModel):
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    designation: Optional[str] = None
    linkedIn: Optional[str] = None
    pan: Optional[str] = None

class ClientContactCreate(ClientContactBase):
    pass

class ClientContactUpdate(ClientContactBase): # New Schema for updating client contacts
    id: Optional[int] = None # Allow ID for existing contacts

class ClientContactOut(ClientContactBase):
    id: int
    client_id: int
    model_config = ConfigDict(from_attributes=True)

# ---------------- USER SCHEMAS ----------------
class UserCreate(BaseModel):
    username: str
    usernumber: str
    email: Optional[str] = None
    department: Optional[str] = None
    password: str
    role: Optional[str] = "Company User"

class UserLogin(BaseModel):
    username: str
    password: str

class UserPasswordChange(BaseModel):
    username: str
    old_password: str
    new_password: str

class UserUpdate(BaseModel):
    username: Optional[str] = None
    usernumber: Optional[str] = None
    email: Optional[str] = None
    department: Optional[str] = None
    role: Optional[str] = None

class UserResponse(BaseModel):
    id: int
    username: str
    usernumber: str
    email: Optional[str]
    department: Optional[str]
    role: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    model_config = ConfigDict(from_attributes=True)


class ActivityLogCreate(BaseModel):
    lead_id: int
    details: str
    phase: str
    activity_type: str = "Call"

class ActivityLogOut(BaseModel):
    id: int
    lead_id: int
    phase: str
    details: str
    attachment_path: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ---------------- LEAD SCHEMAS ----------------
class LeadBase(BaseModel):
    company_name: str
    email: Optional[str] = None
    website: Optional[str] = None # New Field
    linkedIn: Optional[str] = None # New Field
    address: Optional[str] = None
    address_2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    country: Optional[str] = None
    team_size: Optional[Union[str, int]] = None
    source: str
    segment: Optional[str] = None
    verticles: Optional[str] = None
    remark: Optional[str] = None
    product: Optional[str] = None
    phone_2: Optional[str] = None
    turnover: Optional[str] = None
    current_system: Optional[str] = None
    machine_specification: Optional[str] = None
    challenges: Optional[str] = None
    lead_type: Optional[str] = None
    opportunity_business: Optional[str] = None
    target_closing_date: Optional[date] = None

class LeadCreate(LeadBase):
    created_by: str
    assigned_to: str
    contacts: List[ContactCreate]

class LeadResponse(LeadBase):
    id: int
    status: Optional[str]
    assigned_to: str
    created_by: str
    created_at: datetime
    updated_at: Optional[datetime]
    contacts: List[ContactOut] = []

    last_activity: Optional[ActivityLogOut] = None
    model_config = ConfigDict(from_attributes=True)

class LeadUpdateWeb(BaseModel):
    company_name: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None # New Field
    linkedIn: Optional[str] = None # New Field
    address: Optional[str] = None
    address_2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    country: Optional[str] = None
    team_size: Optional[Union[str, int]] = None
    source: Optional[str] = None
    segment: Optional[str] = None
    verticles: Optional[str] = None
    remark: Optional[str] = None
    product: Optional[str] = None
    phone_2: Optional[str] = None
    turnover: Optional[str] = None
    current_system: Optional[str] = None
    machine_specification: Optional[str] = None
    challenges: Optional[str] = None
    lead_type: Optional[str] = None
    assigned_to: Optional[str] = None
    status: Optional[str] = None
    opportunity_business: Optional[str] = None
    target_closing_date: Optional[date] = None
    contacts: List[ContactUpdate] = []
    activity_type: Optional[str] = None
    activity_details: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

# NEW CLIENT SCHEMAS
class ClientBase(BaseModel):
    company_name: str
    website: Optional[str] = None
    linkedIn: Optional[str] = None
    company_email: Optional[str] = None
    company_phone_2: Optional[str] = None
    address: Optional[str] = None
    address_2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    country: Optional[str] = None
    segment: Optional[str] = None
    verticles: Optional[str] = None
    team_size: Optional[Union[str, int]] = None
    turnover: Optional[str] = None
    current_system: Optional[str] = None
    machine_specification: Optional[str] = None
    challenges: Optional[str] = None
    version: Optional[str] = None
    database_type: Optional[str] = None
    amc: Optional[str] = None
    gst: Optional[str] = None
    converted_date: Optional[date] = None

class ClientCreate(ClientBase):
    contacts: List[ClientContactCreate] = [] # Clients can have contacts too

class ClientUpdate(ClientBase): # NEW: Schema for updating existing clients
    company_name: Optional[str] = None # Make company name optional for updates
    contacts: List[ClientContactUpdate] = []
    model_config = ConfigDict(from_attributes=True)

class ClientOut(ClientBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime]
    contacts: List[ClientContactOut] = []
    model_config = ConfigDict(from_attributes=True)

# SCHEMA FOR LEAD CONVERSION PAYLOAD
class ConvertLeadToClientPayload(BaseModel):
    # Fields to potentially update or add during conversion
    company_name: Optional[str] = None
    website: Optional[str] = None
    linkedIn: Optional[str] = None
    company_email: Optional[str] = None
    company_phone_2: Optional[str] = None
    address: Optional[str] = None
    address_2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    country: Optional[str] = None
    segment: Optional[str] = None
    verticles: Optional[str] = None
    team_size: Optional[Union[str, int]] = None
    turnover: Optional[str] = None
    current_system: Optional[str] = None
    machine_specification: Optional[str] = None
    challenges: Optional[str] = None
    version: Optional[str] = None
    database_type: Optional[str] = None
    amc: Optional[str] = None
    gst: Optional[str] = None
    converted_date: Optional[date] = None
    contacts: List[ClientContactCreate] = [] # Use ClientContactCreate for contacts during conversion

# ---------------- TASK SCHEMAS ----------------
class TaskOut(BaseModel):
    id: int
    lead_id: int
    company_name: str
    event_type: str
    event_time: datetime
    remark: str | None = None
    model_config = ConfigDict(from_attributes=True)

# ---------------- EVENT SCHEMAS ----------------
class EventBase(BaseModel):
    lead_id: int
    assigned_to: str
    event_type: str
    meeting_type: Optional[str] = None
    event_time: datetime
    event_end_time: Optional[datetime] = None
    created_by: str
    remark: Optional[str] = None
    phase: Optional[str] = None

class EventCreate(EventBase):
    pass

class EventOut(EventBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

# ---------------- DEMO SCHEMAS ----------------
class DemoOut(BaseModel):
    id: int
    lead_id: int
    scheduled_by: str
    assigned_to: str
    start_time: datetime
    event_end_time: Optional[datetime]
    phase: str
    remark: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]
    model_config = ConfigDict(from_attributes=True)

# ---------------- WEB FORM SCHEMAS ----------------
class MeetingScheduleWeb(BaseModel):
    lead_id: int
    assigned_to_user_id: int
    start_time: datetime
    end_time: datetime
    created_by_user_id: int
    meeting_type: str

class PostMeetingWeb(BaseModel):
    meeting_id: int
    notes: str
    updated_by: str

class DemoScheduleWeb(BaseModel):
    lead_id: int
    assigned_to_user_id: int
    start_time: datetime
    end_time: datetime
    created_by_user_id: int

class PostDemoWeb(BaseModel):
    demo_id: int
    notes: str
    updated_by: str

# ---------------- OTHER SCHEMAS ----------------
class ReminderCreate(BaseModel):
    lead_id: int
    remind_time: datetime
    message: str
    assigned_to: str
    user_id: int
    activity_type: Optional[str] = "Follow-up"
    is_hidden_from_activity_log: Optional[bool] = False # <--- NEW FIELD


class HistoryItemOut(BaseModel):
    timestamp: datetime
    event_type: str
    details: str
    user: str

class AssignmentLogCreate(BaseModel):
    lead_id: int
    assigned_to: str
    assigned_by: str

class MessageMasterBase(BaseModel):
    message_name: str
    message_content: Optional[str] = None
    message_type: str # 'text', 'media', 'document'
    attachment_path: Optional[str] = None

class MessageMasterCreate(MessageMasterBase):
    created_by: str

class MessageMasterUpdate(MessageMasterBase):
    pass

class MessageMasterOut(MessageMasterBase):
    id: int
    message_code: str
    created_at: datetime
    created_by: str

    model_config = ConfigDict(from_attributes=True)

# --- Drip Sequence Schemas ---
class DripSequenceStepBase(BaseModel):
    message_id: int
    day_to_send: int
    time_to_send: time # Use `time` for validation
    sequence_order: int

class DripSequenceStepCreate(DripSequenceStepBase):
    pass

class DripSequenceCreate(BaseModel):
    drip_name: str
    created_by: str
    steps: list[DripSequenceStepCreate]

class DripSequenceStepOut(DripSequenceStepBase):
    id: int
    # Include message details in the response for the frontend
    message: MessageMasterOut

    model_config = ConfigDict(from_attributes=True)

class DripSequenceOut(BaseModel):
    id: int
    drip_code: str
    drip_name: str
    created_at: datetime
    created_by: str
    steps: list[DripSequenceStepOut]

    model_config = ConfigDict(from_attributes=True)

class DripSequenceListOut(BaseModel): # For the main list view
    id: int
    drip_code: str
    drip_name: str
    created_at: datetime
    created_by: str
    model_config = ConfigDict(from_attributes=True)

class ReminderOut(BaseModel):
    id: int
    lead_id: int # We need the lead_id to link back to the lead
    remind_time: datetime
    message: str
    assigned_to: str
    status: str
    created_at: datetime
    is_hidden_from_activity_log: bool # <--- NEW FIELD
    # --- ADD THIS LINE ---
    model_config = ConfigDict(from_attributes=True)

class MarkActivityDonePayload(BaseModel):
    notes: str
    updated_by: str

class UnifiedActivityOut(BaseModel):
    id: int
    type: str  # 'log' or 'reminder'
    lead_id: int
    company_name: str
    activity_type: str
    details: str
    status: str
    created_at: datetime
    scheduled_for: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

class StatusMessage(BaseModel):
    """A generic response model for success/error messages."""
    status: str
    message: str

class ScheduleActivityWeb(BaseModel):
    lead_id: int
    details: str
    activity_type: str
    created_by_user_id: int

class EventReschedulePayload(BaseModel):
    start_time: datetime
    end_time: datetime
    updated_by: str

class EventReassignPayload(BaseModel):
    assigned_to_user_id: int
    updated_by: str

class EventCancelPayload(BaseModel):
    reason: str
    updated_by: str

class EventNotesUpdatePayload(BaseModel):
    notes: str
    updated_by: str


class ActivityLogUpdate(BaseModel):
    details: str
    activity_type: Optional[str] = None