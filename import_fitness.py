"""Importerar Fitness Fight-recept och taggar med clean-protein."""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from app.database import SessionLocal, init_db
from app.models import Tag
from import_folder import import_file

init_db()
db = SessionLocal()

folder = os.path.join(os.environ["USERPROFILE"], "Dropbox", "Recept", "Fitness fight")
skip = ["(kopia)", "KOSTPROGRAM", "ningsprogram", "Recept Oktober", "Fitness Fight recept"]

files = [
    os.path.join(folder, f)
    for f in os.listdir(folder)
    if f.endswith((".docx", ".doc", ".pdf", ".txt"))
    and not any(s in f for s in skip)
    and f != "recept.docx"
    and f != "recept (kopia).docx"
]

print(f"Importerar {len(files)} recept fran Fitness Fight:")
for filepath in sorted(files):
    result = import_file(filepath, db)
    if result and result.get("status") == "imported":
        rid = result["id"]
        existing = [t.tag for t in db.query(Tag).filter(Tag.recipe_id == rid).all()]
        if "clean-protein" not in existing:
            db.add(Tag(recipe_id=rid, tag="clean-protein"))
            db.commit()
    time.sleep(0.5)

db.close()
print("Klart!")
