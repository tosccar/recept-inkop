from fastapi import FastAPI, Request, Depends, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import os
import json
import uuid
from datetime import datetime, timezone

from app.database import get_db, init_db
from app import crud
from app.scraper import extract_recipe_from_url
from app.tags import PREDEFINED_TAGS
from app.ica_deals import fetch_ica_deals, save_deals_to_db
from app.auth import verify_credentials
from app.image_utils import fix_orientation

app = FastAPI(title="Recept & Inköp", dependencies=[Depends(verify_credentials)])

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB

BASE_DIR = os.path.dirname(__file__)
PROJECT_DIR = os.path.dirname(BASE_DIR)
DATA_DIR = os.environ.get("DATA_DIR", PROJECT_DIR)
IMAGES_DIR = os.path.join(DATA_DIR, "recipe_images")
os.makedirs(IMAGES_DIR, exist_ok=True)

PDF_DIR = os.path.join(DATA_DIR, "recipes_pdf")
os.makedirs(PDF_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


@app.on_event("startup")
def startup():
    init_db()





# --- Startsida ---

@app.get("/", response_class=HTMLResponse)
def index(request: Request, search: str = "", category: str = "",
          tag: str = "", sort: str = "name_asc",
          db: Session = Depends(get_db)):
    recipes = crud.get_recipes(db, search=search, category=category, tag=tag, sort=sort)
    total = crud.count_recipes(db)
    categories = crud.get_categories(db)
    return templates.TemplateResponse("index.html", {
        "request": request,
        "recipes": recipes,
        "total": total,
        "categories": categories,
        "predefined_tags": PREDEFINED_TAGS,
        "search": search,
        "selected_category": category,
        "selected_tag": tag,
        "selected_sort": sort,
    })


# --- HTMX: sökresultat ---

@app.get("/htmx/recipes", response_class=HTMLResponse)
def htmx_recipes(request: Request, search: str = "", category: str = "",
                 tag: str = "", sort: str = "name_asc", view: str = "grid",
                 db: Session = Depends(get_db)):
    recipes = crud.get_recipes(db, search=search, category=category, tag=tag, sort=sort)
    total = crud.count_recipes(db)
    return templates.TemplateResponse("_recipe_list.html", {
        "request": request,
        "recipes": recipes,
        "total": total,
        "selected_sort": sort,
        "selected_category": category,
    })


# --- Importera recept från URL ---

@app.get("/api/check-duplicate")
def api_check_duplicate(name: str = "", url: str = "", db: Session = Depends(get_db)):
    """Kollar om ett recept med samma namn eller URL redan finns."""
    from app.models import Recipe
    matches = []
    if name:
        existing = db.query(Recipe).filter(Recipe.name.ilike(name.strip())).all()
        matches.extend([{"id": r.id, "name": r.name, "match": "name"} for r in existing])
    if url:
        existing = db.query(Recipe).filter(Recipe.source_link == url.strip()).all()
        matches.extend([{"id": r.id, "name": r.name, "match": "url"} for r in existing])
    return {"duplicates": matches}


@app.post("/api/extract-url")
def api_extract_url(url: str = Form(...)):
    """Extraherar receptdata från en URL."""
    data = extract_recipe_from_url(url)
    if not data:
        return JSONResponse({"error": "Kunde inte läsa receptet från denna URL."}, status_code=400)
    return data


@app.post("/api/extract-image")
async def api_extract_image(file: UploadFile = File(...)):
    """Analyserar receptbild med Claude API. Fallback: returnerar OCR-text for granskning."""
    from app.image_analyzer import analyze_with_claude, extract_text_from_image
    allowed = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
    if file.content_type not in allowed:
        return JSONResponse({"error": "Otillåten filtyp. Använd JPG, PNG eller WebP."}, status_code=400)

    image_data = await file.read()
    if len(image_data) > MAX_UPLOAD_SIZE:
        return JSONResponse({"error": "Filen är för stor. Max 10 MB."}, status_code=413)

    # Spara bilden
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "jpg"
    if ext not in ("jpg", "jpeg", "png", "webp"):
        ext = "jpg"
    filename = f"new_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = os.path.join(IMAGES_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(image_data)

    image_path = f"/images/{filename}"

    # Försök med Claude API först
    data = analyze_with_claude(image_data, file.content_type)
    if data and "error" not in data:
        data["image_path"] = image_path
        return data

    # Fallback: OCR + returnera text för granskning
    ocr_text = extract_text_from_image(image_data)
    if ocr_text and len(ocr_text.strip()) >= 10:
        return {"ocr_text": ocr_text, "image_path": image_path, "needs_review": True}

    error_msg = data.get("error", "Kunde inte tolka bilden.") if data else "Kunde inte tolka bilden."
    return JSONResponse({"error": error_msg}, status_code=400)


@app.post("/api/structure-recipe")
def api_structure_recipe(ocr_text: str = Form(...)):
    """Fallback steg 2: Strukturerar granskad OCR-text till receptdata."""
    from app.image_analyzer import structure_text_to_recipe
    data = structure_text_to_recipe(ocr_text)
    if not data:
        return JSONResponse({"error": "Kunde inte tolka texten som recept."}, status_code=400)
    if "error" in data and len(data) == 1:
        return JSONResponse({"error": data["error"]}, status_code=400)
    return data


# --- Lägg till recept ---

@app.get("/add", response_class=HTMLResponse)
def add_form(request: Request):
    return templates.TemplateResponse("add.html", {
        "request": request,
        "predefined_tags": PREDEFINED_TAGS,
    })


@app.post("/add")
async def add_recipe(
    request: Request,
    name: str = Form(...),
    source_type: str = Form("url"),
    source_link: str = Form(""),
    pdf_path: str = Form(""),
    image_path: str = Form(""),
    servings: int = Form(4),
    category: str = Form(""),
    notes: str = Form(""),
    ingredients_json: str = Form("[]"),
    db: Session = Depends(get_db),
):
    form = await request.form()
    tags_list = form.getlist("tags")
    tags_str = ", ".join(tags_list)
    ingredients = json.loads(ingredients_json)
    recipe = crud.create_recipe(
        db, name=name, source_type=source_type, source_link=source_link,
        pdf_path=pdf_path, servings=servings, category=category, notes=notes,
        ingredients=ingredients, tags_str=tags_str,
    )
    # Spara bild om uppladdad
    if image_path:
        recipe.image_path = image_path
        db.commit()
    return RedirectResponse(f"/recipe/{recipe.id}", status_code=303)


# --- Visa recept ---

@app.get("/recipe/{recipe_id}", response_class=HTMLResponse)
def detail(request: Request, recipe_id: int, db: Session = Depends(get_db)):
    recipe = crud.get_recipe(db, recipe_id)
    if not recipe:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("detail.html", {
        "request": request,
        "recipe": recipe,
    })


# --- Betygsätt ---

@app.post("/recipe/{recipe_id}/rate")
def rate_recipe(
    recipe_id: int,
    score: int = Form(...),
    comment: str = Form(""),
    db: Session = Depends(get_db),
):
    crud.add_rating(db, recipe_id=recipe_id, score=score, comment=comment)
    return RedirectResponse(f"/recipe/{recipe_id}", status_code=303)


# --- Redigera ---

@app.get("/recipe/{recipe_id}/edit", response_class=HTMLResponse)
def edit_form(request: Request, recipe_id: int, db: Session = Depends(get_db)):
    recipe = crud.get_recipe(db, recipe_id)
    if not recipe:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("edit.html", {
        "request": request,
        "recipe": recipe,
        "predefined_tags": PREDEFINED_TAGS,
    })


@app.post("/recipe/{recipe_id}/edit")
async def edit_recipe(
    request: Request,
    recipe_id: int,
    name: str = Form(...),
    source_type: str = Form("url"),
    source_link: str = Form(""),
    servings: int = Form(4),
    category: str = Form(""),
    notes: str = Form(""),
    ingredients_json: str = Form("[]"),
    db: Session = Depends(get_db),
):
    form = await request.form()
    tags_list = form.getlist("tags")
    tags_str = ", ".join(tags_list)
    ingredients = json.loads(ingredients_json)
    crud.update_recipe(
        db, recipe_id=recipe_id, name=name, source_type=source_type,
        source_link=source_link, servings=servings, category=category,
        notes=notes, ingredients=ingredients, tags_str=tags_str,
    )
    return RedirectResponse(f"/recipe/{recipe_id}", status_code=303)


# --- Rotera bild ---

@app.post("/api/rotate-image/{recipe_id}")
def api_rotate_image(recipe_id: int, db: Session = Depends(get_db)):
    """Roterar receptbilden 90 grader medurs."""
    from PIL import Image
    import io
    from app.models import Recipe
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe or not recipe.image_path:
        return JSONResponse({"error": "Ingen bild"}, status_code=404)

    filename = os.path.basename(recipe.image_path)
    search_paths = [
        os.path.join(IMAGES_DIR, filename),
        os.path.join(DATA_DIR, "recipe_images", filename),
    ]
    filepath = None
    for p in search_paths:
        if os.path.exists(p):
            filepath = p
            break
    if not filepath:
        return JSONResponse({"error": "Bildfil saknas"}, status_code=404)

    img = Image.open(filepath)
    img = img.rotate(-90, expand=True)
    if img.mode == "RGBA":
        img = img.convert("RGB")
    img.save(filepath, format="JPEG", quality=85)

    return {"status": "ok", "image_url": recipe.image_path}


# --- Lägg till på inköpslista från receptsidan ---

@app.post("/recipe/{recipe_id}/add-to-list")
def add_recipe_to_list(recipe_id: int, servings: int = Form(4),
                       db: Session = Depends(get_db)):
    crud.add_recipe_to_shopping_list(db, recipe_id, servings)
    return RedirectResponse(f"/recipe/{recipe_id}?added=1", status_code=303)


# --- Visa sparad fil ---

@app.get("/recipe/{recipe_id}/file")
def serve_recipe_file(recipe_id: int, db: Session = Depends(get_db)):
    """Servar den sparade filen (PDF, Word, bild) för ett recept."""
    from fastapi.responses import FileResponse
    recipe = crud.get_recipe(db, recipe_id)
    if not recipe or not recipe.pdf_path:
        return RedirectResponse(f"/recipe/{recipe_id}", status_code=303)

    filename = recipe.pdf_path
    # Sök filen i DATA_DIR/recipes_pdf/ och lokalt
    search_paths = [
        os.path.join(DATA_DIR, "recipes_pdf", filename),
        os.path.join(PDF_DIR, filename),
        filename,  # Absolut sökväg (bakåtkompatibilitet)
    ]
    for filepath in search_paths:
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            return FileResponse(filepath)

    return RedirectResponse(f"/recipe/{recipe_id}", status_code=303)


# --- Ta bort ---

@app.post("/recipe/{recipe_id}/delete")
def delete_recipe(recipe_id: int, db: Session = Depends(get_db)):
    crud.delete_recipe(db, recipe_id)
    return RedirectResponse("/", status_code=303)


# --- Bilduppladdning ---

@app.post("/api/upload-image/{recipe_id}")
async def api_upload_image(recipe_id: int, file: UploadFile = File(...),
                           db: Session = Depends(get_db)):
    """Tar emot en bild (drag-n-drop eller kamera) och sparar till recept."""
    from app.models import Recipe
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        return JSONResponse({"error": "Recept hittades inte"}, status_code=404)

    # Validera filtyp
    allowed = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
    if file.content_type not in allowed:
        return JSONResponse({"error": "Otillåten filtyp. Använd JPG, PNG eller WebP."}, status_code=400)

    # Spara filen
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "jpg"
    if ext not in ("jpg", "jpeg", "png", "webp"):
        ext = "jpg"
    filename = f"{recipe_id}_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = os.path.join(IMAGES_DIR, filename)

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        return JSONResponse({"error": "Filen är för stor. Max 10 MB."}, status_code=413)
    content = fix_orientation(content)
    filename = f"{recipe_id}_{uuid.uuid4().hex[:8]}.jpg"  # Alltid JPEG efter rotation
    filepath = os.path.join(IMAGES_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(content)

    # Ta bort gammal bild om den finns
    if recipe.image_path:
        old_path = os.path.join(IMAGES_DIR, os.path.basename(recipe.image_path))
        if os.path.exists(old_path):
            os.remove(old_path)

    recipe.image_path = f"/images/{filename}"
    db.commit()

    return {"image_url": recipe.image_path}


@app.post("/api/upload-image-new")
async def api_upload_image_new(file: UploadFile = File(...)):
    """Laddar upp en bild for ett recept som inte ar sparat annu. Returnerar sokvag."""
    allowed = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
    if file.content_type not in allowed:
        return JSONResponse({"error": "Otillåten filtyp"}, status_code=400)

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "jpg"
    if ext not in ("jpg", "jpeg", "png", "webp"):
        ext = "jpg"
    filename = f"new_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = os.path.join(IMAGES_DIR, filename)

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        return JSONResponse({"error": "Filen är för stor. Max 10 MB."}, status_code=413)
    content = fix_orientation(content)
    filename = f"new_{uuid.uuid4().hex[:8]}.jpg"
    filepath = os.path.join(IMAGES_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(content)

    return {"image_url": f"/images/{filename}"}


# --- Veckoförslag ---

@app.get("/suggestions", response_class=HTMLResponse)
def suggestions_page(request: Request, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    year, week, _ = now.isocalendar()
    current = crud.get_suggestions(db, year=year, week=week)
    history = crud.get_all_suggestions(db, limit=20)
    profile = crud.get_taste_profile(db)
    return templates.TemplateResponse("suggestions.html", {
        "request": request,
        "current_suggestions": current,
        "history": history,
        "profile": profile,
        "week": week,
        "year": year,
    })


@app.post("/suggestions/{suggestion_id}/accept")
def accept_suggestion(suggestion_id: int, db: Session = Depends(get_db)):
    crud.update_suggestion_status(db, suggestion_id, "accepted")
    return RedirectResponse("/suggestions", status_code=303)


@app.post("/suggestions/{suggestion_id}/reject")
def reject_suggestion(suggestion_id: int, db: Session = Depends(get_db)):
    crud.update_suggestion_status(db, suggestion_id, "rejected")
    return RedirectResponse("/suggestions", status_code=303)


# --- API: Smakprofil (för schemalagd uppgift) ---

@app.get("/api/taste-profile")
def api_taste_profile(db: Session = Depends(get_db)):
    return crud.get_taste_profile(db)


@app.post("/api/suggestions")
def api_create_suggestion(
    recipe_name: str = Form(...),
    description: str = Form(""),
    reason: str = Form(""),
    source_url: str = Form(""),
    category: str = Form(""),
    week_number: int = Form(0),
    year: int = Form(0),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    if not week_number:
        week_number = now.isocalendar()[1]
    if not year:
        year = now.isocalendar()[0]
    suggestion = crud.create_suggestion(
        db, recipe_name=recipe_name, description=description,
        reason=reason, source_url=source_url, category=category,
        week_number=week_number, year=year,
    )
    return {"id": suggestion.id, "status": "created"}


# --- Erbjudanden ---

@app.get("/deals", response_class=HTMLResponse)
def deals_page(request: Request, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    year, week, _ = now.isocalendar()
    deals = crud.get_current_deals(db)
    matches = crud.match_recipes_to_deals(db)
    return templates.TemplateResponse("deals.html", {
        "request": request,
        "deals": deals,
        "matches": matches,
        "week": week,
        "year": year,
    })


# --- API: Deals (för schemalagd uppgift / Claude in Chrome) ---

@app.get("/api/deals")
def api_get_deals(db: Session = Depends(get_db)):
    deals = crud.get_current_deals(db)
    return [{"id": d.id, "product": d.product_name, "price": d.price,
             "original_price": d.original_price} for d in deals]


@app.post("/api/deals")
def api_create_deal(
    product_name: str = Form(...),
    price: str = Form(""),
    original_price: str = Form(""),
    week_number: int = Form(0),
    year: int = Form(0),
    valid_from: str = Form(""),
    valid_to: str = Form(""),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    if not week_number:
        week_number = now.isocalendar()[1]
    if not year:
        year = now.isocalendar()[0]
    deal = crud.create_deal(
        db, product_name=product_name, price=price,
        original_price=original_price, week_number=week_number,
        year=year, valid_from=valid_from, valid_to=valid_to,
    )
    return {"id": deal.id, "status": "created"}


@app.post("/api/deals/fetch-ica")
async def api_fetch_ica_deals(db: Session = Depends(get_db)):
    """Hämtar erbjudanden från ICA Maxi Östersund via deras publika API."""
    import asyncio
    loop = asyncio.get_event_loop()
    deals = await loop.run_in_executor(None, fetch_ica_deals)
    if not deals:
        return JSONResponse(
            {"error": "Kunde inte hämta erbjudanden från ICA. Försök igen senare."},
            status_code=502,
        )
    result = save_deals_to_db(db, deals)
    return result


@app.post("/deals/fetch", response_class=HTMLResponse)
async def deals_fetch_and_redirect(db: Session = Depends(get_db)):
    """Hämtar ICA-erbjudanden och redirectar tillbaka till deals-sidan."""
    import asyncio
    loop = asyncio.get_event_loop()
    deals = await loop.run_in_executor(None, fetch_ica_deals)
    if deals:
        save_deals_to_db(db, deals)
    return RedirectResponse("/deals", status_code=303)


@app.post("/api/deals/clear-week")
def api_clear_deals(
    week_number: int = Form(0),
    year: int = Form(0),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    if not week_number:
        week_number = now.isocalendar()[1]
    if not year:
        year = now.isocalendar()[0]
    count = crud.clear_deals_for_week(db, year, week_number)
    return {"cleared": count, "week": week_number, "year": year}


@app.get("/api/deals/matches")
def api_deal_matches(db: Session = Depends(get_db)):
    matches = crud.match_recipes_to_deals(db)
    result = []
    for m in matches:
        result.append({
            "recipe_name": m["recipe"].name,
            "recipe_id": m["recipe"].id,
            "category": m["recipe"].category,
            "avg_rating": m["recipe"].avg_rating,
            "matched_count": m["matched_count"],
            "total_ingredients": m["total_ingredients"],
            "match_pct": m["match_pct"],
            "matched_ingredients": m["matched_ingredients"],
        })
    return result


# --- Veckomeny ---

@app.get("/menu", response_class=HTMLResponse)
def menu_page(request: Request, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    year, week, _ = now.isocalendar()
    slots = crud.get_menu(db, year=year, week=week)
    deals = crud.get_current_deals(db)
    deal_map = crud.get_ingredient_deal_map(db)
    # Bygg ingredient->deal matchning per slot
    slot_deals = _build_slot_deals(slots, deal_map)
    return templates.TemplateResponse("menu.html", {
        "request": request,
        "slots": slots,
        "week": week,
        "year": year,
        "has_deals": len(deals) > 0,
        "has_recipes": crud.count_recipes(db) > 0,
        "slot_deals": slot_deals,
    })


def _build_slot_deals(slots, deal_map):
    """Bygger en dict: ingredient_id -> deal_info för alla slots."""
    result = {}
    for slot in slots:
        if not slot.recipe or not slot.recipe.ingredients:
            continue
        for ing in slot.recipe.ingredients:
            match = crud.match_ingredient_to_deal(ing.name, deal_map)
            if match:
                result[ing.id] = match
    return result


@app.post("/menu/generate", response_class=HTMLResponse)
def menu_generate(db: Session = Depends(get_db)):
    crud.generate_menu(db)
    return RedirectResponse("/menu", status_code=303)


@app.post("/htmx/menu/reroll/{slot_id}", response_class=HTMLResponse)
def htmx_reroll(request: Request, slot_id: int, db: Session = Depends(get_db)):
    """HTMX: byter ut ett recept i en menyplats och returnerar uppdaterat kort."""
    slot = crud.reroll_slot(db, slot_id)
    if not slot:
        return HTMLResponse("")
    return templates.TemplateResponse("_menu_card.html", {
        "request": request,
        "slot": slot,
        "slot_deals": _build_slot_deals([slot], crud.get_ingredient_deal_map(db)),
    })


@app.post("/htmx/menu/servings/{slot_id}", response_class=HTMLResponse)
def htmx_update_servings(request: Request, slot_id: int,
                          servings: int = Form(...),
                          db: Session = Depends(get_db)):
    """HTMX: uppdaterar portioner för en menyplats."""
    slot = crud.update_slot_servings(db, slot_id, servings)
    if not slot:
        return HTMLResponse("")
    return templates.TemplateResponse("_menu_card.html", {
        "request": request,
        "slot": slot,
        "slot_deals": _build_slot_deals([slot], crud.get_ingredient_deal_map(db)),
    })


@app.post("/htmx/menu/add-to-list/{slot_id}", response_class=HTMLResponse)
def htmx_add_to_list(request: Request, slot_id: int, db: Session = Depends(get_db)):
    """HTMX: lägger till ingredienser från en menyplats på inköpslistan."""
    from app.models import MenuSlot
    slot = db.query(MenuSlot).filter(MenuSlot.id == slot_id).first()
    if slot:
        crud.add_recipe_to_shopping_list(db, slot.recipe_id, slot.servings)
    return templates.TemplateResponse("_menu_card.html", {
        "request": request,
        "slot": slot,
        "just_added": True,
        "slot_deals": _build_slot_deals([slot], crud.get_ingredient_deal_map(db)),
    })


# --- Inköpslista ---

@app.get("/shopping-list", response_class=HTMLResponse)
def shopping_list_page(request: Request, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    year, week, _ = now.isocalendar()
    items = crud.get_shopping_list(db, year=year, week=week)

    # Gruppera efter recept
    groups: dict[str, list] = {}
    for item in items:
        key = item.recipe_name or "Övrigt"
        if key not in groups:
            groups[key] = []
        groups[key].append(item)

    return templates.TemplateResponse("shopping_list.html", {
        "request": request,
        "groups": groups,
        "total_items": len(items),
        "checked_items": sum(1 for i in items if i.checked),
        "week": week,
        "year": year,
    })


@app.post("/htmx/shopping-list/toggle/{item_id}", response_class=HTMLResponse)
def htmx_toggle_item(request: Request, item_id: int, db: Session = Depends(get_db)):
    """HTMX: bocka av/på en ingrediens."""
    item = crud.toggle_shopping_item(db, item_id)
    if not item:
        return HTMLResponse("")
    return templates.TemplateResponse("_shopping_item.html", {
        "request": request,
        "item": item,
    })


@app.post("/shopping-list/clear", response_class=HTMLResponse)
def clear_shopping(db: Session = Depends(get_db)):
    crud.clear_shopping_list(db)
    return RedirectResponse("/shopping-list", status_code=303)


@app.post("/htmx/shopping-list/remove/{item_id}", response_class=HTMLResponse)
def htmx_remove_item(item_id: int, db: Session = Depends(get_db)):
    crud.remove_shopping_item(db, item_id)
    return HTMLResponse("")
