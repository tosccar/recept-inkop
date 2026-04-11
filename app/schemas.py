from pydantic import BaseModel
from typing import Optional


class IngredientForm(BaseModel):
    name: str
    quantity: Optional[str] = None
    group_name: Optional[str] = None


class RecipeCreate(BaseModel):
    name: str
    source_type: Optional[str] = "url"
    source_link: Optional[str] = None
    servings: Optional[int] = 4
    category: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[str] = ""  # comma-separated
    ingredients: list[IngredientForm] = []


class RatingCreate(BaseModel):
    score: int  # 1-5
    comment: Optional[str] = None
