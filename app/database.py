from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

# Stöd för Render persistent disk via DATA_DIR
DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.dirname(__file__)))
DB_PATH = os.path.join(DATA_DIR, "recipes.db")
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app.models import Recipe, Ingredient, Tag, Rating, Suggestion, Deal, FamilyPreference, MenuSlot, ShoppingItem, DealMatch  # noqa: F401
    Base.metadata.create_all(bind=engine)
    # Seed default family preferences if empty
    db = SessionLocal()
    try:
        if db.query(FamilyPreference).count() == 0:
            defaults = [
                FamilyPreference(key="laktosfri", value="true"),
                FamilyPreference(key="ej_stark", value="true"),
                FamilyPreference(key="standard_portioner", value="4"),
            ]
            db.add_all(defaults)
            db.commit()
    finally:
        db.close()
