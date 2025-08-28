# app/schemas.py
from pydantic import BaseModel, ConfigDict
from typing import Optional, Union
from datetime import datetime

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

# ---------------- LEAD SCHEMAS ----------------
class LeadBase(BaseModel):
    company_name: str
    contact_name: str
    phone: str
    email: Optional[str] = None
    address: Optional[str] = None
    team_size: Optional[Union[str, int]] = None
    source: str
    segment: Optional[str] = None
    remark: Optional[str] = None
    product: Optional[str] = None
    phone_2: Optional[str] = None
    turnover: Optional[str] = None
    current_system: Optional[str] = None
    machine_specification: Optional[str] = None
    challenges: Optional[str] = None
    lead_type: Optional[str] = None

class LeadCreate(LeadBase):
    created_by: str
    assigned_to: Optional[str]

class LeadOut(LeadBase):
    id: int
    status: str
    created_at: datetime
    assigned_to: Optional[str]
    model_config = ConfigDict(from_attributes=True)

class LeadUpdateWeb(BaseModel):
    company_name: Optional[str] = None
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    team_size: Optional[Union[str, int]] = None
    source: Optional[str] = None
    segment: Optional[str] = None
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
    model_config = ConfigDict(from_attributes=True)

class LeadResponse(BaseModel):
    id: int
    company_name: str
    contact_name: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    address: Optional[str]
    source: Optional[str]
    segment: Optional[str]
    team_size: Optional[str]
    remark: Optional[str]
    status: Optional[str]
    assigned_to: str
    created_by: str
    created_at: datetime
    updated_at: Optional[datetime]
    phone_2: Optional[str]
    turnover: Optional[str]
    current_system: Optional[str]
    machine_specification: Optional[str]
    challenges: Optional[str]
    lead_type: Optional[str]
    model_config = ConfigDict(from_attributes=True)

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
    event_time: datetime
    event_end_time: Optional[datetime] = None
    created_by: str
    remark: Optional[str] = None

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

class ActivityLogCreate(BaseModel):
    lead_id: int
    details: str
    phase: str

class ActivityLogOut(BaseModel):
    id: int
    lead_id: int
    phase: str
    details: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class HistoryItemOut(BaseModel):
    timestamp: datetime
    event_type: str
    details: str
    user: str

class AssignmentLogCreate(BaseModel):
    lead_id: int
    assigned_to: str
    assigned_by: str