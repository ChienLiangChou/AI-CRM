from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

import os
from pathlib import Path


def _resolve_database_url(env=os.environ, path_exists=None) -> str:
    """Choose a stable local CRM database unless an explicit URL is configured."""
    explicit_url = env.get("DATABASE_URL")
    if explicit_url:
        return explicit_url

    configured_data_dir = env.get("SKC_DATA_DIR")
    if configured_data_dir:
        return f"sqlite:///{Path(configured_data_dir).expanduser() / 'sql_app.db'}"

    exists = path_exists or (lambda path: Path(path).exists())
    local_data_dir = Path.home() / "SKC Agent OS" / "backend"
    if exists(local_data_dir):
        return f"sqlite:///{local_data_dir / 'sql_app.db'}"

    if exists(Path("/data")):
        return "sqlite:////data/sql_app.db"

    return "sqlite:///sql_app.db"


SQLALCHEMY_DATABASE_URL = _resolve_database_url()

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
