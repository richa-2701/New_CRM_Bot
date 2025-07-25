### **Project Documentation: AI-Powered Conversational CRM Bot**

**Version:** 1.0
**Last Updated:** July 24, 2025

---

### **1. Project Overview**

This project is an intelligent, AI-driven Customer Relationship Management (CRM) bot that operates entirely within WhatsApp. It is designed to replace traditional, manual CRM data entry by allowing a sales team to manage the entire lead lifecycle through simple, natural language commands in English, Hindi, or Hinglish.

The system acts as a central hub, capturing all interactions, automating workflows, and ensuring timely follow-ups. By leveraging Artificial Intelligence (OpenAI's GPT-4o), the bot can understand unstructured messages, extract relevant data, and trigger the appropriate actions, effectively turning WhatsApp into an active, intelligent assistant for the sales team. It includes a robust API for a frontend application to visualize leads, tasks, and the complete history of any lead.

### **2. Core Goal**

The primary goal of the project is to dramatically **increase the efficiency and effectiveness of the sales team** by solving several key problems:

*   **Eliminate Manual Data Entry:** Remove the need for salespeople to log into a separate CRM system. All updates are made by "chatting" with the bot.
*   **Centralize Communication:** Consolidate all lead-related information, notes, and status changes in a single, searchable system, preventing data from being scattered across phone calls, texts, and emails.
*   **Automate Workflows and Handoffs:** Automatically assign new leads, schedule follow-ups, and notify team members of new responsibilities, ensuring a smooth and rapid progression through the sales pipeline.
*   **Ensure Consistent Follow-Up:** Implement an automated lead nurturing system (the "Message Master") to guarantee that no lead is forgotten after a demo.
*   **Provide Complete Visibility:** Create a comprehensive, chronological history for every lead, allowing team leaders and members to see every action, status change, and note from creation to completion.

### **3. Technical Architecture**

#### **3.1. Technology Stack**

*   **Backend Framework:** FastAPI (Python)
*   **Database:** Microsoft SQL Server (MSSQL)
*   **ORM:** SQLAlchemy
*   **AI Parser:** OpenAI GPT-4o
*   **Messaging API:** Maytapi for WhatsApp integration
*   **Environment Configuration:** Pydantic and `.env` files

#### **3.2. Folder Structure**

```
NEW_CRM_BOT/
├── main.py                  # FastAPI application entry point
├── requirements.txt         # Project dependencies
├── .env                     # Environment variables (DB URL, API keys)
└── app/
    ├── __init__.py
    ├── config.py            # Pydantic settings management
    ├── db.py                # Database engine and session setup
    ├── crud.py              # Core database functions (Create, Read, Update, Delete)
    ├── models.py            # SQLAlchemy ORM models (database tables)
    ├── schemas.py           # Pydantic schemas (data validation and serialization)
    ├── webhook.py           # API router for all incoming requests
    ├── message_router.py    # Main logic to route messages to the correct handler
    ├── message_sender.py    # Unified function to send replies via WhatsApp or App
    ├── gpt_parser.py        # All GPT-4o prompt logic for parsing messages
    └── handlers/
        ├── __init__.py
        ├── lead_handler.py
        ├── qualification_handler.py
        ├── meeting_handler.py
        ├── demo_handler.py
        ├── reassignment_handler.py
        ├── activity_handler.py
        └── ... (other specific handlers)
```

### **4. Automated Workflow**

The bot is designed to manage a specific, multi-stage sales process, automating each step of a lead's journey:

1.  **Lead Intake:**
    *   A team member sends a message with new lead details.
    *   The AI Parser extracts the company name, contact info, source, and assigned user.
    *   The system creates the lead in the database, automatically assigning it to the designated user.
    *   An activity is logged: "Lead created by [User] and assigned to [Assignee]."
    *   The creator gets a confirmation, and the new assignee receives a WhatsApp notification.

2.  **Lead Qualification:**
    *   A team member sends a message like "Lead qualified for [Company Name]".
    *   The bot updates the lead's status to "Qualified" and logs this change as an activity.
    *   It then checks the lead's record for any missing information (e.g., turnover, current system, challenges).
    *   If details are missing, the bot interactively asks the user to provide them. The user can reply with the information in a single message, 
        which is then parsed and saved.

3.  **Meeting & Demo Management:**
    *   Users can schedule meetings or demos using commands like "Schedule meeting with [Company] on [Date/Time] assigned to [User]".
    *   The bot parses all details, creates an event in the database, and notifies the assignee.
    *   When a meeting or demo is completed, a user sends "Meeting done for [Company]". The bot updates the lead's status and logs the event as an 
        activity.
    *   Rescheduling and reassignments are also handled via simple commands and are automatically logged in the activity history.

4.  **Automated Lead Nurturing (The "Message Master"):**
    *   Immediately after a demo is marked "Done", the system triggers a pre-defined follow-up sequence.
    *   It fetches a series of messages from the `message_master` table, each with a specific delay (e.g., Day 1, Day 3, Day 7).
    *   It then schedules a series of reminders for the lead's assignee.
    *   At the scheduled time, the assignee receives a WhatsApp message from the bot containing the exact, pre-written text (and any attachments) 
        that they should copy or forward to the client.

### **5. API Routes**

All API endpoints are defined in `app/webhook.py`.

| Method | Endpoint                       | Description                                                                                              |
| :----- | :----------------------------- | :------------------------------------------------------------------------------------------------------- |
| `POST` | `/register`                    | Creates a new user in the system.                                                                        |
| `POST` | `/login`                       | Authenticates a user and returns their details.                                                          |
| `GET`  | `/leads/{user_id}`             | Fetches all leads assigned to a specific user.                                                           |
| `GET`  | `/tasks/{username}`            | Fetches all upcoming tasks (Events) for a user, including the company name.                              |
| `GET`  | `/activities/{lead_id}`        | Fetches a simple log of all manual and automated activities for a specific lead.                         |
| `GET`  | `/history/{lead_id}`           | **(For Frontend)** Fetches a complete, unified, and chronologically sorted history of a lead.            |
| `POST` | `/webhook`                     | **(For Maytapi)** The primary endpoint for receiving incoming WhatsApp messages.                         |
| `POST` | `/app`                         | **(For Frontend)** The endpoint for receiving commands from a custom web or mobile application.          |

### **6. Conversational Commands**

The bot is designed to understand a variety of natural language commands. Below are some examples:

*   **New Lead:**
    *   `New lead: [Company], [Contact], [Phone], [Source], [Assignee]`
    *   `There is a lead from [Company Name], contact is [Name] ([Phone]), assign to [User].`

*   **Qualification:**
    *   `Lead qualified for [Company Name]`
    *   (In response to a prompt for details): `Address: [Address], Turnover: [Amount], Challenges: [Details]`

*   **Scheduling:**
    *   `Schedule meeting with [Company] on [Date/Time] assigned to [User]`
    *   `Schedule demo for [Company] on [Date/Time]`
    *   `Reschedule meeting for [Company] on [New Date/Time]`

*   **Updates:**
    *   `Meeting done for [Company]. They were very interested.`
    *   `Demo done for [Company].`

*   **Activity Logging:**
    *   `Add activity for [Company], Called the client, they asked for a new proposal.`

*   **Reassignment:**
    *   `Reassign [Company] to [New User]`

### **7. Setup and Deployment**

1.  **Prerequisites:**
    *   Python 3.10+
    *   Microsoft SQL Server
    *   Access to Maytapi (or another WhatsApp API provider)
    *   OpenAI API Key

2.  **Installation:**
    *   Clone the repository.
    *   Create a virtual environment: `python -m venv venv`
    *   Activate the environment: `source venv/bin/activate` (or `venv\Scripts\activate` on Windows)
    *   Install dependencies: `pip install -r requirements.txt`

3.  **Environment Configuration:**
    *   Create a file named `.env` in the project root.
    *   Add the following variables:
        ```env
        DATABASE_URL="mssql+pyodbc://USER:PASSWORD@SERVER/DATABASE?driver=ODBC+Driver+17+for+SQL+Server"
        OPENAI_API_KEY="your_openai_api_key"
        MAYT_API_URL="your_maytapi_reply_url"
        MAYT_API_TOKEN="your_maytapi_token"
        ```

4.  **Running the Application:**
    *   Use Uvicorn to run the FastAPI server:
        ```bash
        uvicorn main:app --host 0.0.0.0 --port 8000 --reload
        ```

### **8. Executive Summary**

In essence, this project transforms WhatsApp from a simple communication tool into the central nervous system of a sales operation. It leverages 
cutting-edge AI to create a frictionless, conversational interface that aligns with the natural workflow of a sales team.

By automating data entry, lead assignment, status updates, and post-demo follow-ups, the system removes significant administrative overhead. This 
frees up the sales team to focus on what they do best: building relationships and closing deals. The comprehensive activity and history tracking 
provides management with unprecedented, real-time visibility into the sales pipeline. The result is a more efficient, consistent, and data-driven 
sales process that is poised to improve response times, increase engagement, and ultimately drive revenue.