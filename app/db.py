# app/db.py
import os
import urllib
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.orm import Session
from dotenv import load_dotenv
# --- START OF CHANGE ---
from fastapi import Request, HTTPException
# --- END OF CHANGE ---


# Load .env variables
load_dotenv()

# --- START OF CHANGE: DYNAMIC ENGINE MANAGEMENT FOR MULTI-TENANCY ---

# This dictionary will cache engine objects once they are created to avoid
# recreating them for every request, improving performance.
_engines = {}

# This map defines which environment variable holds the connection string for each company.
# The key is the company_name the user will provide.
# The value is the name of the variable in your .env file.
COMPANY_TO_ENV_MAP = {
    'Indas Analytics': 'DB_CONN_DEFAULT',
    'Amar Ujala': 'DB_CONN_AMAR_UJALA',
}

def get_engine(company_name: str):
    """
    Creates and caches a database engine for a specific company.
    Raises an error if the company is not configured.
    """
    # 1. Return cached engine if it exists
    if company_name in _engines:
        return _engines[company_name]

    # 2. Find the correct environment variable for the company
    env_var_name = COMPANY_TO_ENV_MAP.get(company_name)
    if not env_var_name:
        raise HTTPException(
            status_code=400,
            detail=f"Configuration for company '{company_name}' not found."
        )

    # 3. Load the connection string from environment variables
    conn_str = os.getenv(env_var_name)
    if not conn_str:
        raise ValueError(f"Environment variable '{env_var_name}' not found for company '{company_name}'")

    # 4. Create, cache, and return the new engine
    params = urllib.parse.quote_plus(conn_str)
    engine = create_engine(f"mssql+pyodbc:///?odbc_connect={params}", echo=True)
    _engines[company_name] = engine
    
    print(f"Successfully created engine for company: {company_name}")
    return engine

# --- THIS IS THE CENTRAL BASE ---
# All models will import this Base to register themselves.
Base = declarative_base()


# NEW: Dependency for authenticated endpoints.
# This function will be used for every API call AFTER a user has logged in.
# It requires the frontend to send the user's company name in a custom header.
def get_db(request: Request):
    """
    FastAPI dependency that provides a DB session based on the 'X-Company-Name' header.
    """
    company_name = request.headers.get("X-Company-Name")
    if not company_name:
        raise HTTPException(
            status_code=400,
            detail="Request is missing the required 'X-Company-Name' header."
        )

    try:
        engine = get_engine(company_name)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db: Session = SessionLocal()
        try:
            yield db
        finally:
            db.close()
    except (HTTPException, ValueError) as e:
        # Re-raise exceptions from get_engine
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection failed for company '{company_name}': {str(e)}")


# NEW: Helper function to get a session manually for login/register.
# This is NOT a dependency. It's called directly from the endpoints.
def get_db_session_for_company(company_name: str) -> Session:
    """
    Creates a new database session for a specific company.
    This should be used in a try/finally block.
    """
    engine = get_engine(company_name)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()

# --- END OF CHANGE ---