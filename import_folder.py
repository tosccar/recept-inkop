r"""Importerar recept fran en mapp med filer (PDF, Word, bilder, text).

Anvandning:
    python import_folder.py "C:\Users\CarinaOscarsson\Dropbox\Recept\Kyckling"
    python import_folder.py "C:\Users\CarinaOscarsson\Dropbox\Recept"  --recursive
"""
import sys
import os
import json
import time
import shutil
import base64
import re
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv()

import fitz
from app.file_importer import extract_text_from_file, guess_category_from_folder, get_recipe_name_from_file, convert_to_pdf
from app.database import SessionLocal, init_db
from app import crud

SUPPORTED_EXT = {".pdf", ".doc", ".docx", ".txt", ".jpg", ".jpeg", ".png"}
SKIP_FOLDERS = {"0 dieter kostinformation", "fitness fight", ".appledouble"}
FILES_DIR = os.path.join(os.path.dirname(__file__), "recipes_pdf")


def _copy_file_to_project(filepath: str) -> str:
    """Kopierar originalfilen till recipe_files/. Returnerar relativ sokvag."""
    src = Path(filepath)
    # Skapa unikt filnamn
    safe_name = re.sub(r'[^\w\s\-.]', '', src.name).strip()
    dest = Path(FILES_DIR) / safe_name
    # Hantera namnkollision
    counter = 1
    while dest.exists():
        stem = re.sub(r'[^\w\s\-.]', '', src.stem).strip()
        dest = Path(FILES_DIR) / f"{stem}_{counter}{src.suffix}"
        counter += 1
    shutil.copy2(str(src), str(dest))
    return str(dest)


def analyze_text_with_claude(text: str, filename: str, folder_category: str) -> dict | None:
    """Skickar extraherad text till Claude API."""
    import anthropic

    prompt = f"""Analysera denna recepttext och returnera BARA ett JSON-objekt:
{{
    "name": "Receptets namn",
    "servings": 4,
    "category": "{folder_category}" om det stammer, annars valj bland: fisk, fars, korv, kott, kyckling, vegetariskt, pasta, soppa, sallad, dryck, forratt, efterratt, kakor/tartor, snacks, ovrigt,
    "ingredients": [
        {{"name": "ingrediensnamn", "quantity": "mangd med enhet", "group_name": "grupp"}}
    ],
    "instructions": "Tillagningsinstruktioner",
    "notes": ""
}}

group_name: kott & fisk, mejeri, gronsaker, frukt, torrvaror, kryddor, ovrigt.
Skriv allt pa svenska med korrekt anvandning av a, a, o. Returnera BARA JSON.

Filnamn: {filename}
Text:
{text[:4000]}"""

    try:
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        return _parse_json_response(msg.content[0].text)
    except Exception as e:
        print(f"  Claude-fel: {e}")
    return None


def _resize_if_needed(image_data: bytes, max_bytes: int = 4_500_000) -> bytes:
    """Krymper bilden om den överskrider max_bytes."""
    if len(image_data) <= max_bytes:
        return image_data
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(image_data))
    # Krympa tills den är under gränsen
    quality = 85
    while quality > 20:
        buf = io.BytesIO()
        if img.mode == 'RGBA':
            img = img.convert('RGB')
        w, h = img.size
        if len(image_data) > max_bytes * 2:
            img = img.resize((w // 2, h // 2), Image.LANCZOS)
        img.save(buf, format='JPEG', quality=quality)
        if buf.tell() <= max_bytes:
            return buf.getvalue()
        quality -= 15
    return buf.getvalue()


def analyze_image_with_claude(filepath: str, folder_category: str) -> dict | None:
    """Analyserar receptbild med Claude Vision."""
    import anthropic

    with open(filepath, "rb") as f:
        image_data = f.read()
    image_data = _resize_if_needed(image_data)

    ext = Path(filepath).suffix.lower()
    media_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
    media_type = media_map.get(ext, "image/jpeg")
    b64 = base64.standard_b64encode(image_data).decode("utf-8")

    prompt = f"""Analysera receptbilden. Returnera BARA JSON:
{{
    "name": "Receptets namn",
    "servings": 4,
    "category": "{folder_category}" om det stammer, annars valj ratt kategori,
    "ingredients": [{{"name": "namn", "quantity": "mangd", "group_name": "grupp"}}],
    "instructions": "Tillagning",
    "notes": ""
}}
group_name: kott & fisk, mejeri, gronsaker, frukt, torrvaror, kryddor, ovrigt.
Skriv allt pa svenska med korrekt anvandning av a, a, o. BARA JSON."""

    try:
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        return _parse_json_response(msg.content[0].text)
    except Exception as e:
        print(f"  Claude Vision-fel: {e}")
    return None


def _parse_json_response(text: str) -> dict | None:
    text = text.strip()
    if "```" in text:
        lines = [l for l in text.split("\n") if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass
    return None


def _analyze_pdf_as_image(filepath: str, folder_category: str) -> dict | None:
    """Konverterar forsta sidan av en PDF till bild och analyserar."""
    try:
        doc = fitz.open(filepath)
        page = doc[0]
        pix = page.get_pixmap(dpi=200)
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        pix.save(tmp.name)
        doc.close()
        result = analyze_image_with_claude(tmp.name, folder_category)
        os.unlink(tmp.name)
        return result
    except Exception as e:
        print(f"  PDF-till-bild-fel: {e}")
        return None


def import_file(filepath: str, db) -> dict | None:
    """Importerar en enskild fil."""
    filename = Path(filepath).name
    folder_category = guess_category_from_folder(filepath)
    ext = Path(filepath).suffix.lower()

    print(f"  {filename}...", end=" ", flush=True)

    # Kolla om receptet redan finns
    recipe_name = get_recipe_name_from_file(filepath)
    from app.models import Recipe
    existing = db.query(Recipe).filter(Recipe.name.ilike(f"%{recipe_name[:30]}%")).first()
    if existing:
        print(f"FINNS REDAN ({existing.name})")
        return {"status": "exists", "name": existing.name}

    # Bilder: Claude Vision
    if ext in (".jpg", ".jpeg", ".png"):
        data = analyze_image_with_claude(filepath, folder_category)
    else:
        text = extract_text_from_file(filepath)
        if not text:
            if ext == ".pdf":
                data = _analyze_pdf_as_image(filepath, folder_category)
            else:
                print("KUNDE INTE LASA")
                return {"status": "failed", "name": filename}
        else:
            data = analyze_text_with_claude(text, filename, folder_category)

    if not data or "error" in data:
        print("KUNDE INTE TOLKA")
        return {"status": "failed", "name": filename}

    # Kopiera originalfil och konvertera till PDF om det är Word/text
    local_copy = _copy_file_to_project(filepath)
    if ext in (".doc", ".docx", ".txt"):
        pdf_copy = convert_to_pdf(filepath, FILES_DIR)
        if pdf_copy:
            local_copy = pdf_copy

    # Taggar
    from app.tags import suggest_tags
    raw_ings = [f"{i.get('quantity','')} {i.get('name','')}".strip() for i in data.get("ingredients", [])]
    tags = suggest_tags(data.get("name", ""), raw_ings, data.get("category", ""))

    recipe = crud.create_recipe(
        db,
        name=data.get("name", recipe_name),
        source_type="file",
        source_link=filepath,
        pdf_path=local_copy,
        servings=data.get("servings", 4),
        category=data.get("category", folder_category),
        notes=data.get("instructions", ""),
        ingredients=data.get("ingredients", []),
        tags_str=", ".join(tags),
    )

    print(f"OK: {recipe.name} ({len(data.get('ingredients', []))} ingredienser)")
    return {"status": "imported", "name": recipe.name, "id": recipe.id}


def import_folder(folder_path: str, recursive: bool = False):
    """Importerar alla receptfiler i en mapp."""
    init_db()
    db = SessionLocal()

    folder = Path(folder_path)
    if not folder.exists():
        print(f"Mappen finns inte: {folder_path}")
        return

    if recursive:
        files = []
        for root, dirs, filenames in os.walk(folder):
            dir_name = Path(root).name.lower()
            if dir_name in SKIP_FOLDERS:
                continue
            for f in filenames:
                if Path(f).suffix.lower() in SUPPORTED_EXT:
                    files.append(os.path.join(root, f))
    else:
        files = [str(f) for f in folder.iterdir() if f.suffix.lower() in SUPPORTED_EXT]

    print(f"\n{'='*60}")
    print(f"Importerar {len(files)} filer")
    print(f"{'='*60}\n")

    results = {"imported": 0, "exists": 0, "failed": 0}

    for filepath in sorted(files):
        result = import_file(filepath, db)
        if result:
            results[result["status"]] = results.get(result["status"], 0) + 1
        time.sleep(0.5)

    db.close()

    print(f"\n{'='*60}")
    print(f"Klart!")
    print(f"  Importerade: {results['imported']}")
    print(f"  Redan finns: {results['exists']}")
    print(f"  Misslyckade: {results['failed']}")
    print(f"{'='*60}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("python import_folder.py <mapp> [--recursive]")
        sys.exit(1)

    folder = sys.argv[1]
    recursive = "--recursive" in sys.argv
    import_folder(folder, recursive)
