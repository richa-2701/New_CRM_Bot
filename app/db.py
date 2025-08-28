import os
import urllib
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.orm import Session
from dotenv import load_dotenv


# Load .env variables
load_dotenv()

# Read connection string from .env and URL encode it
conn_str = os.getenv("DB_CONN")
if not conn_str:
    raise ValueError("DB_CONN not found in environment variables")
    
params = urllib.parse.quote_plus(conn_str)

# Create engine
engine = create_engine(f"mssql+pyodbc:///?odbc_connect={params}", echo=True)

# Create session and base
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# --- THIS IS THE CENTRAL BASE ---
# All models will import this Base to register themselves.
Base = declarative_base()


# Dependency function to provide DB session
def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()