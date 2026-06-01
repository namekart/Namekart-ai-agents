from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings

def get_engine():
    # DATA_SOURCE=file → no DB engine needed (queries.py reads CSV instead)
    # DATA_SOURCE=temp → local MySQL with seed data
    # DATA_SOURCE=prod → company MySQL amp2
    if settings.data_source == "file":
        return None
    url = settings.db_url_temp if settings.data_source == "temp" else settings.db_url_prod
    if not url:
        return None
    return create_engine(url, pool_pre_ping=True)

engine = get_engine()
SessionLocal = sessionmaker(bind=engine) if engine else None

def get_session():
    if not SessionLocal:
        return None
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
