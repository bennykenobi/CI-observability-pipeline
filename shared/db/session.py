"""SQLAlchemy engine and session factory for the platform database."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from shared.config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, class_=Session)
