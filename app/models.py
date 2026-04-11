from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from app.database import Base


class Recipe(Base):
    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    source_type = Column(String, default="url")  # url, pdf, docx, text
    source_link = Column(Text)  # Originallänk
    pdf_path = Column(Text)  # Lokal PDF-kopia
    image_path = Column(Text)  # Lokal receptbild
    servings = Column(Integer, default=4)
    category = Column(String, index=True)  # fisk, kött, kyckling, veg, pasta...
    notes = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    ingredients = relationship("Ingredient", back_populates="recipe", cascade="all, delete-orphan")
    tags = relationship("Tag", back_populates="recipe", cascade="all, delete-orphan")
    ratings = relationship("Rating", back_populates="recipe", cascade="all, delete-orphan")

    @property
    def avg_rating(self):
        if not self.ratings:
            return None
        return sum(r.score for r in self.ratings) / len(self.ratings)

    @property
    def latest_rating(self):
        if not self.ratings:
            return None
        return sorted(self.ratings, key=lambda r: r.rated_at, reverse=True)[0]


class Ingredient(Base):
    __tablename__ = "ingredients"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    name = Column(String, nullable=False, index=True)
    quantity = Column(String)
    group_name = Column(String)  # mejeri, kött, grönsaker...

    recipe = relationship("Recipe", back_populates="ingredients")


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    tag = Column(String, nullable=False, index=True)

    recipe = relationship("Recipe", back_populates="tags")


class Rating(Base):
    __tablename__ = "ratings"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    score = Column(Integer, nullable=False)  # 1-5
    comment = Column(Text)
    rated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    recipe = relationship("Recipe", back_populates="ratings")


class Suggestion(Base):
    __tablename__ = "suggestions"

    id = Column(Integer, primary_key=True, index=True)
    recipe_name = Column(String, nullable=False)
    description = Column(Text)  # Kort beskrivning av receptet
    reason = Column(Text)  # Varför detta föreslås ("Ni gillar kyckling...")
    source_url = Column(Text)  # Länk till recept
    category = Column(String)
    week_number = Column(Integer, nullable=False)
    year = Column(Integer, nullable=False)
    status = Column(String, default="new")  # new, accepted, rejected
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Deal(Base):
    __tablename__ = "deals"

    id = Column(Integer, primary_key=True, index=True)
    product_name = Column(String, nullable=False, index=True)
    price = Column(String)  # T.ex. "29 kr/kg", "2 för 50 kr"
    original_price = Column(String)  # Ordinarie pris om känt
    week_number = Column(Integer, nullable=False)
    year = Column(Integer, nullable=False)
    valid_from = Column(String)  # Datum som text
    valid_to = Column(String)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class FamilyPreference(Base):
    __tablename__ = "family_preferences"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, nullable=False, unique=True)
    value = Column(Text)


class MenuSlot(Base):
    """En plats i veckomenyn (5 st per vecka)."""
    __tablename__ = "menu_slots"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    slot_number = Column(Integer, nullable=False)  # 1-5
    servings = Column(Integer, default=4)
    week_number = Column(Integer, nullable=False)
    year = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    recipe = relationship("Recipe")


class ShoppingItem(Base):
    """En rad på inköpslistan."""
    __tablename__ = "shopping_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    quantity = Column(String)
    recipe_name = Column(String)  # Vilket recept den kom från
    checked = Column(Integer, default=0)  # 0=ej avbockad, 1=avbockad
    week_number = Column(Integer, nullable=False)
    year = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
