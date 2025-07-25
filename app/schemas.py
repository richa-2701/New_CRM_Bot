# app/schemas.py
from pydantic import BaseModel, ConfigDict
from typing import Optional, Union
from datetime import datetime
from app.models import LeadStatus, TaskStatus
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
    product: Optional[str] = None  # optional for future use
    phone_2: Optional[str] = None
    turnover: Optional[str] = None
    current_system: Optional[str] = None
    machine_specification: Optional[str] = None
    challenges: Optional[str] = None
    # --- END NEW FIELDS ---

class LeadCreate(LeadBase):
    created_by: str
    assigned_to: Optional[str]  # FK to users.id
class LeadOut(LeadBase):
    id: int
    status: str
    created_at: datetime
    assigned_to: Optional[str]
    model_config = ConfigDict(from_attributes=True)
class LeadUpdate(BaseModel):
    status: Optional[str]
    remark: Optional[str] = None
    assigned_to: Optional[int]

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
    updated_at: Optional[datetime] = None
    
    # --- NEW OPTIONAL FIELDS ---
    phone_2: Optional[str] = None
    turnover: Optional[str] = None
    current_system: Optional[str] = None
    machine_specification: Optional[str] = None
    challenges: Optional[str] = None
    # --- END NEW FIELDS ---

# ---------------- TASK SCHEMAS ----------------
class TaskBase(BaseModel):
    lead_id: int
    assigned_to: str
    task_type: str
    date_time: datetime
    remark: Optional[str] = None
class TaskCreate(TaskBase):
    pass

class TaskOut(BaseModel):
    id: int
    lead_id: int
    company_name: str
    event_type: str
    event_time: datetime
    remark: str | None = None

    class Config:
        orm_mode = True
# ---------------- USER SCHEMAS ----------------
class UserBase(BaseModel):
    username: str
    usernumber: str
    department: Optional[str] = None
class UserCreate(BaseModel):
    username: str
    usernumber: str
    email: Optional[str] = None
    department: Optional[str] = None
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class UserResponse(BaseModel):
    id: int
    username: str
    usernumber: str
    email: Optional[str] = None 
    department: Optional[str]

    class Config:
        orm_mode = True

class UserOut(UserBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
# ---------------- EVENT SCHEMAS ----------------
class EventBase(BaseModel):
    lead_id: int
    assigned_to: str
    event_type: str
    event_time: datetime
    created_by: str
    remark: Optional[str] = None
class EventCreate(EventBase):
    pass
class EventOut(EventBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
# ---------------- FEEDBACK SCHEMAS ----------------
class FeedbackBase(BaseModel):
    lead_id: int
    feedback_by: str
    content: str
class FeedbackCreate(FeedbackBase):
    pass
class FeedbackOut(FeedbackBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
# ---------------- REMINDER SCHEMAS ----------------


class ReminderBase(BaseModel):
    lead_id: int
    remind_time: datetime
    message: str
    assigned_to: str
class ReminderCreate(ReminderBase):
    user_id: int  # required for FK to users.id
class ReminderOut(ReminderBase):
    id: int
    status: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
    
# ---------------- ACTIVITY LOG SCHEMAS ----------------
class ActivityLogBase(BaseModel):
    lead_id: int
    details: str

class ActivityLogCreate(ActivityLogBase):
    phase: str

class ActivityLogOut(ActivityLogBase):
    id: int
    phase: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

# --- NEW SCHEMA FOR UNIFIED LEAD HISTORY ---
class HistoryItemOut(BaseModel):
    timestamp: datetime
    event_type: str  # e.g., "Creation", "Status Change", "Activity", "Reassignment"
    details: str
    user: str


class AssignmentLogBase(BaseModel):
    lead_id: int
    assigned_to: str
    assigned_by: str

class AssignmentLogCreate(AssignmentLogBase):
    pass

class AssignmentLogOut(AssignmentLogBase):
    id: int
    assigned_at: datetime
    model_config = ConfigDict(from_attributes=True)