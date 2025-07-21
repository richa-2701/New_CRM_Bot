# db.py
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
params = urllib.parse.quote_plus(conn_str)

# Create engine
engine = create_engine(f"mssql+pyodbc:///?odbc_connect={params}", echo=True)

# Create session and base
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Dependency function to provide DB session
def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
