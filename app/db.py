import os
import urllib
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from fastapi import Request, HTTPException

# Load .env variables
load_dotenv()

# --- START: DYNAMIC ENGINE MANAGEMENT FOR MULTI-TENANCY ---

# This dictionary caches engine objects to improve performance.
_engines = {}

# This map defines which environment variable holds the connection string for each company.
# The key is the company_name the user will provide.
# The value is the name of the variable in your .env file.
COMPANY_TO_ENV_MAP = {
    'Indas Analytics': 'DB_CONN_DEFAULT',
    'Amar Ujala': 'DB_CONN_AMAR_UJALA',
    # Add more company mappings here as needed
}

def get_engine(company_name: str):
    """
    Creates and caches a database engine for a specific company.
    Raises an HTTPException if the company is not configured.
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
    try:
        params = urllib.parse.quote_plus(conn_str)
        engine = create_engine(f"mssql+pyodbc:///?odbc_connect={params}")
        # Test connection
        connection = engine.connect()
        connection.close()
        _engines[company_name] = engine
        print(f"Successfully created and cached engine for company: {company_name}")
        return engine
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to connect to the database for company '{company_name}'. Please check the connection string.")


# This is the central Base for all SQLAlchemy models.
Base = declarative_base()


def get_db(request: Request):
    """
    FastAPI dependency that provides a DB session based on the 'X-Company-Name' header.
    This is used for all authenticated web API calls.
    """
    company_name = request.headers.get("X-Company-Name")
    if not company_name:
        raise HTTPException(
            status_code=400,
            detail="Request is missing the required 'X-Company-Name' header."
        )

    db: Session = None
    try:
        engine = get_engine(company_name)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = SessionLocal()
        yield db
    except (HTTPException, ValueError) as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection failed for company '{company_name}': {str(e)}")
    finally:
        if db:
            db.close()


def get_db_session_for_company(company_name: str) -> Session:
    """
    Creates a new database session for a specific company.
    This is used manually for login, registration, and the WhatsApp webhook.
    It's crucial to use this in a try/finally block to ensure the session is closed.
    """
    try:
        engine = get_engine(company_name)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        return SessionLocal()
    except (HTTPException, ValueError) as e:
        # Re-raise exceptions from get_engine to be handled by the caller
        raise e
    except Exception as e:
        # Catch other potential errors during session creation
        raise HTTPException(status_code=500, detail=f"Failed to create a database session for company '{company_name}'.")

# --- END: DYNAMIC ENGINE MANAGEMENT FOR MULTI-TENANCY ---