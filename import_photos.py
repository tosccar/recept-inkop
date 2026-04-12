"""Importerar receptfoton via Claude API bildanalys."""
import sys
import os
import time
import glob

sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from app.database import SessionLocal, init_db
from app import crud
from app.models import Tag
from app.image_analyzer import analyze_with_claude
from app.scraper import _generate_recipe_pdf
from app.tags import suggest_tags

init_db()
db = SessionLocal()

folder = os.path.join(os.environ["USERPROFILE"], "Downloads")
files = sorted(glob.glob(os.path.join(folder, "IMG_129*.JPEG")) +
               glob.glob(os.path.join(folder, "IMG_130*.JPEG")) +
               glob.glob(os.path.join(folder, "IMG_131*.JPEG")))

print(f"Importerar {len(files)} receptfoton via Claude API:")
results = {"ok": 0, "exists": 0, "failed": 0}

for filepath in files:
    filename = os.path.basename(filepath)
    print(f"  {filename}...", end=" ", flush=True)

    with open(filepath, "rb") as f:
        image_data = f.read()

    # Analysera med Claude API
    data = analyze_with_claude(image_data, "image/jpeg")
    if not data or "error" in data:
        err = data.get("error", "okänt fel") if data else "inget svar"
        print(f"FEL: {err}")
        results["failed"] += 1
        time.sleep(1)
        continue

    recipe_name = data.get("name", "")
    if not recipe_name:
        print("INGET NAMN")
        results["failed"] += 1
        continue

    # Kolla duplikat
    from app.models import Recipe
    existing = db.query(Recipe).filter(Recipe.name.ilike(f"%{recipe_name[:30]}%")).first()
    if existing:
        print(f"FINNS REDAN ({existing.name})")
        results["exists"] += 1
        time.sleep(0.5)
        continue

    # Kopiera bilden
    import shutil
    img_dest = os.path.join(os.path.dirname(__file__), "recipe_images", filename)
    shutil.copy2(filepath, img_dest)
    image_path = f"/images/{filename}"

    # Skapa recept
    ingredients = data.get("ingredients", [])
    raw_ings = [f"{i.get('quantity','')} {i.get('name','')}".strip() for i in ingredients]
    tags = suggest_tags(recipe_name, raw_ings, data.get("category", ""))

    recipe = crud.create_recipe(
        db,
        name=recipe_name,
        source_type="foto",
        source_link=filepath,
        pdf_path="",
        servings=data.get("servings", 4),
        category=data.get("category", ""),
        notes=data.get("instructions", ""),
        ingredients=ingredients,
        tags_str=", ".join(tags),
    )

    # Spara bild
    recipe.image_path = image_path
    db.commit()

    print(f"OK: {recipe_name} ({len(ingredients)} ingredienser)")
    results["ok"] += 1
    time.sleep(1)  # Rate limiting

db.close()
print(f"\nKlart! Importerade: {results['ok']}, fanns redan: {results['exists']}, misslyckade: {results['failed']}")
