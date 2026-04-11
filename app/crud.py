from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func
from datetime import datetime, timezone

import random
from app.models import Recipe, Ingredient, Tag, Rating, Suggestion, Deal, FamilyPreference, MenuSlot, ShoppingItem


def get_recipes(db: Session, search: str = "", category: str = "",
                tag: str = "", sort: str = "name_asc"):
    query = db.query(Recipe).options(
        joinedload(Recipe.ingredients),
        joinedload(Recipe.tags),
        joinedload(Recipe.ratings),
    )

    if search:
        search_term = f"%{search}%"
        query = query.outerjoin(Ingredient).outerjoin(Tag).filter(
            or_(
                Recipe.name.ilike(search_term),
                Ingredient.name.ilike(search_term),
                Tag.tag.ilike(search_term),
            )
        )

    if category:
        query = query.filter(Recipe.category == category)

    if tag:
        if not search:  # undvik dubbel outerjoin
            query = query.outerjoin(Tag)
        query = query.filter(Tag.tag == tag)

    # Sortering
    sort_map = {
        "name_asc": Recipe.name.asc(),
        "name_desc": Recipe.name.desc(),
        "category_asc": Recipe.category.asc(),
        "category_desc": Recipe.category.desc(),
        "rating_desc": Recipe.id,  # placeholder, sorteras nedan
        "rating_asc": Recipe.id,
        "servings_asc": Recipe.servings.asc(),
        "servings_desc": Recipe.servings.desc(),
        "newest": Recipe.created_at.desc(),
        "oldest": Recipe.created_at.asc(),
        "updated": Recipe.updated_at.desc(),
    }
    # Betygsortering görs i Python (avg_rating är en property)
    if sort in ("rating_desc", "rating_asc"):
        recipes = query.distinct().all()
        reverse = sort == "rating_desc"
        recipes.sort(key=lambda r: r.avg_rating or 0, reverse=reverse)
        return recipes

    order = sort_map.get(sort, Recipe.name.asc())
    return query.distinct().order_by(order).all()


def count_recipes(db: Session) -> int:
    return db.query(Recipe).count()


def get_recipe(db: Session, recipe_id: int):
    return db.query(Recipe).options(
        joinedload(Recipe.ingredients),
        joinedload(Recipe.tags),
        joinedload(Recipe.ratings),
    ).filter(Recipe.id == recipe_id).first()


def create_recipe(db: Session, name: str, source_type: str, source_link: str,
                   servings: int, category: str, notes: str,
                   ingredients: list[dict], tags_str: str,
                   pdf_path: str = "") -> Recipe:
    recipe = Recipe(
        name=name,
        source_type=source_type,
        source_link=source_link or None,
        pdf_path=pdf_path or None,
        servings=servings,
        category=category or None,
        notes=notes or None,
    )
    db.add(recipe)
    db.flush()

    for ing in ingredients:
        if ing.get("name", "").strip():
            db.add(Ingredient(
                recipe_id=recipe.id,
                name=ing["name"].strip(),
                quantity=ing.get("quantity", "").strip() or None,
                group_name=ing.get("group_name", "").strip() or None,
            ))

    if tags_str:
        for tag_name in tags_str.split(","):
            tag_name = tag_name.strip().lower()
            if tag_name:
                db.add(Tag(recipe_id=recipe.id, tag=tag_name))

    db.commit()
    db.refresh(recipe)
    return recipe


def update_recipe(db: Session, recipe_id: int, name: str, source_type: str,
                   source_link: str, servings: int, category: str, notes: str,
                   ingredients: list[dict], tags_str: str) -> Recipe | None:
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        return None

    recipe.name = name
    recipe.source_type = source_type
    recipe.source_link = source_link or None
    recipe.servings = servings
    recipe.category = category or None
    recipe.notes = notes or None

    # Replace ingredients
    db.query(Ingredient).filter(Ingredient.recipe_id == recipe_id).delete()
    for ing in ingredients:
        if ing.get("name", "").strip():
            db.add(Ingredient(
                recipe_id=recipe.id,
                name=ing["name"].strip(),
                quantity=ing.get("quantity", "").strip() or None,
                group_name=ing.get("group_name", "").strip() or None,
            ))

    # Replace tags
    db.query(Tag).filter(Tag.recipe_id == recipe_id).delete()
    if tags_str:
        for tag_name in tags_str.split(","):
            tag_name = tag_name.strip().lower()
            if tag_name:
                db.add(Tag(recipe_id=recipe.id, tag=tag_name))

    db.commit()
    db.refresh(recipe)
    return recipe


def delete_recipe(db: Session, recipe_id: int) -> bool:
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        return False
    db.delete(recipe)
    db.commit()
    return True


def add_rating(db: Session, recipe_id: int, score: int, comment: str = "") -> Rating:
    rating = Rating(
        recipe_id=recipe_id,
        score=max(1, min(5, score)),
        comment=comment or None,
    )
    db.add(rating)
    db.commit()
    db.refresh(rating)
    return rating


def get_categories(db: Session) -> list[str]:
    results = db.query(Recipe.category).filter(
        Recipe.category.isnot(None)
    ).distinct().order_by(Recipe.category).all()
    return [r[0] for r in results]


# --- Suggestions ---

def get_suggestions(db: Session, year: int = 0, week: int = 0):
    now = datetime.now(timezone.utc)
    if not year:
        year = now.isocalendar()[0]
    if not week:
        week = now.isocalendar()[1]
    return db.query(Suggestion).filter(
        Suggestion.year == year,
        Suggestion.week_number == week,
    ).order_by(Suggestion.created_at.desc()).all()


def get_all_suggestions(db: Session, limit: int = 20):
    return db.query(Suggestion).order_by(
        Suggestion.year.desc(), Suggestion.week_number.desc(), Suggestion.created_at.desc()
    ).limit(limit).all()


def create_suggestion(db: Session, recipe_name: str, description: str,
                       reason: str, source_url: str, category: str,
                       week_number: int, year: int) -> Suggestion:
    suggestion = Suggestion(
        recipe_name=recipe_name,
        description=description,
        reason=reason,
        source_url=source_url or None,
        category=category or None,
        week_number=week_number,
        year=year,
    )
    db.add(suggestion)
    db.commit()
    db.refresh(suggestion)
    return suggestion


def update_suggestion_status(db: Session, suggestion_id: int, status: str) -> Suggestion | None:
    suggestion = db.query(Suggestion).filter(Suggestion.id == suggestion_id).first()
    if suggestion:
        suggestion.status = status
        db.commit()
        db.refresh(suggestion)
    return suggestion


# --- Taste profile ---

def get_taste_profile(db: Session) -> dict:
    """Analyserar familjens smakprofil baserat på betyg och preferenser."""
    recipes = db.query(Recipe).options(
        joinedload(Recipe.ingredients),
        joinedload(Recipe.tags),
        joinedload(Recipe.ratings),
    ).all()

    # Samla data
    category_scores: dict[str, list[int]] = {}
    ingredient_scores: dict[str, list[int]] = {}
    all_comments: list[dict] = []
    top_recipes: list[dict] = []
    low_recipes: list[dict] = []

    for recipe in recipes:
        if not recipe.ratings:
            continue

        avg = recipe.avg_rating
        cat = recipe.category or "okategoriserad"

        if cat not in category_scores:
            category_scores[cat] = []
        category_scores[cat].append(round(avg))

        for ing in recipe.ingredients:
            name = ing.name.lower()
            if name not in ingredient_scores:
                ingredient_scores[name] = []
            ingredient_scores[name].append(round(avg))

        for rating in recipe.ratings:
            if rating.comment:
                all_comments.append({
                    "recipe": recipe.name,
                    "score": rating.score,
                    "comment": rating.comment,
                })

        if avg >= 4:
            top_recipes.append({"name": recipe.name, "category": cat, "avg": avg})
        elif avg <= 2:
            low_recipes.append({"name": recipe.name, "category": cat, "avg": avg})

    # Beräkna snitt per kategori
    category_avg = {
        cat: round(sum(scores) / len(scores), 1)
        for cat, scores in category_scores.items()
    }

    # Hämta familjeinställningar
    prefs = db.query(FamilyPreference).all()
    preferences = {p.key: p.value for p in prefs}

    return {
        "preferences": preferences,
        "category_averages": category_avg,
        "top_recipes": sorted(top_recipes, key=lambda r: r["avg"], reverse=True),
        "low_recipes": low_recipes,
        "comments": all_comments,
        "total_recipes": len(recipes),
        "total_rated": sum(1 for r in recipes if r.ratings),
    }


# --- Deals ---

def get_current_deals(db: Session) -> list[Deal]:
    now = datetime.now(timezone.utc)
    year, week, _ = now.isocalendar()
    return db.query(Deal).filter(
        Deal.year == year,
        Deal.week_number == week,
    ).order_by(Deal.product_name).all()


def get_deals_by_week(db: Session, year: int, week: int) -> list[Deal]:
    return db.query(Deal).filter(
        Deal.year == year,
        Deal.week_number == week,
    ).order_by(Deal.product_name).all()


def create_deal(db: Session, product_name: str, price: str,
                 original_price: str, week_number: int, year: int,
                 valid_from: str = "", valid_to: str = "") -> Deal:
    deal = Deal(
        product_name=product_name,
        price=price,
        original_price=original_price or None,
        week_number=week_number,
        year=year,
        valid_from=valid_from or None,
        valid_to=valid_to or None,
    )
    db.add(deal)
    db.commit()
    db.refresh(deal)
    return deal


def clear_deals_for_week(db: Session, year: int, week: int) -> int:
    count = db.query(Deal).filter(
        Deal.year == year,
        Deal.week_number == week,
    ).delete()
    db.commit()
    return count


def match_recipes_to_deals(db: Session) -> list[dict]:
    """Matchar recept mot veckans erbjudanden. Returnerar recept rankade efter antal träffar."""
    deals = get_current_deals(db)
    if not deals:
        return []

    deal_names = [d.product_name.lower() for d in deals]
    deal_map = {d.product_name.lower(): d for d in deals}

    recipes = db.query(Recipe).options(
        joinedload(Recipe.ingredients),
        joinedload(Recipe.tags),
        joinedload(Recipe.ratings),
    ).all()

    matches = []
    for recipe in recipes:
        matched_ingredients = []
        for ing in recipe.ingredients:
            ing_name = ing.name.lower()
            for deal_name in deal_names:
                # Flexibel matchning: ingrediensnamn finns i deal eller tvärtom
                if ing_name in deal_name or deal_name in ing_name:
                    matched_ingredients.append({
                        "ingredient": ing.name,
                        "deal": deal_map[deal_name].product_name,
                        "price": deal_map[deal_name].price,
                        "original_price": deal_map[deal_name].original_price,
                    })
                    break

        if matched_ingredients:
            matches.append({
                "recipe": recipe,
                "matched_count": len(matched_ingredients),
                "total_ingredients": len(recipe.ingredients),
                "matched_ingredients": matched_ingredients,
                "match_pct": round(len(matched_ingredients) / max(len(recipe.ingredients), 1) * 100),
            })

    # Sortera: flest matchade ingredienser först, sedan efter betyg
    matches.sort(key=lambda m: (
        m["matched_count"],
        m["recipe"].avg_rating or 0,
    ), reverse=True)

    return matches


def get_ingredient_deal_map(db: Session) -> dict[str, dict]:
    """Returnerar en dict som mappar ingrediensnamn (lowercase) till deal-info.

    Exempel: {"bacon": {"deal": "Bacon, Scan, 420 g", "price": "2 för 74 kr"}}
    """
    deals = get_current_deals(db)
    if not deals:
        return {}

    result = {}
    deal_entries = [(d.product_name, d.product_name.lower(), d.price, d.original_price) for d in deals]

    # Bygg en cache av vanliga ingrediensord mot deals
    for deal_name, deal_lower, price, orig_price in deal_entries:
        # Varje ord i deal-namnet kan vara en ingrediens-match
        for word in deal_lower.split(",")[0].split():
            if len(word) >= 3:
                result[word] = {
                    "deal": deal_name,
                    "price": price,
                    "original_price": orig_price,
                }
        # Hela första delen (produktnamnet före märke)
        short_name = deal_lower.split(",")[0].strip()
        result[short_name] = {
            "deal": deal_name,
            "price": price,
            "original_price": orig_price,
        }

    return result


def match_ingredient_to_deal(ing_name: str, deal_map: dict) -> dict | None:
    """Matchar en ingrediens mot deal-mappen."""
    ing_lower = ing_name.lower().strip()

    # Exakt match
    if ing_lower in deal_map:
        return deal_map[ing_lower]

    # Ingrediensnamnet finns i ett deal-namn
    for key, deal in deal_map.items():
        if ing_lower in key or key in ing_lower:
            return deal

    return None


# --- Veckomeny ---

# Kategorier som får ingå i veckomenyn
_MENU_CATEGORIES = {
    "fisk", "kött", "färs", "korv", "kyckling",
    "vegetariskt", "pasta", "soppa", "sallad",
}


def get_menu(db: Session, year: int = 0, week: int = 0) -> list[MenuSlot]:
    now = datetime.now(timezone.utc)
    if not year:
        year = now.isocalendar()[0]
    if not week:
        week = now.isocalendar()[1]
    return db.query(MenuSlot).filter(
        MenuSlot.year == year,
        MenuSlot.week_number == week,
    ).order_by(MenuSlot.slot_number).all()


def generate_menu(db: Session, count: int = 5) -> list[MenuSlot]:
    """Genererar en veckomeny med recept som matchar veckans erbjudanden.

    Prioriterar recept med flest deals-matchningar, sprider kategorier,
    och fyller på med högt betygsatta recept om det behövs.
    """
    now = datetime.now(timezone.utc)
    year, week, _ = now.isocalendar()

    # Rensa befintlig meny för veckan
    db.query(MenuSlot).filter(
        MenuSlot.year == year, MenuSlot.week_number == week,
    ).delete()

    # Hämta deals-matchningar
    matches = match_recipes_to_deals(db)

    # Alla recept som kandidater — bara middagskategorier
    all_recipes = db.query(Recipe).options(
        joinedload(Recipe.ingredients),
        joinedload(Recipe.ratings),
    ).filter(Recipe.category.in_(_MENU_CATEGORIES)).all()

    # Bygg kandidatlista: deals-matchade först, sedan resten
    matched_ids = {m["recipe"].id for m in matches}
    candidates = []

    # Deals-matchade, sorterade efter matchning + betyg
    for m in matches:
        if m["recipe"].category in _MENU_CATEGORIES:
            candidates.append(m["recipe"])

    # Övriga, sorterade efter betyg
    rest = [r for r in all_recipes if r.id not in matched_ids]
    rest.sort(key=lambda r: r.avg_rating or 0, reverse=True)
    candidates.extend(rest)

    # Välj recept med kategori-spridning
    selected = _pick_varied(candidates, count)

    # Skapa menu slots
    pref = db.query(FamilyPreference).filter(
        FamilyPreference.key == "standard_portioner"
    ).first()
    default_servings = int(pref.value) if pref else 4

    slots = []
    for i, recipe in enumerate(selected, 1):
        slot = MenuSlot(
            recipe_id=recipe.id,
            slot_number=i,
            servings=default_servings,
            week_number=week,
            year=year,
        )
        db.add(slot)
        slots.append(slot)

    db.commit()
    for s in slots:
        db.refresh(s)
    return slots


def reroll_slot(db: Session, slot_id: int) -> MenuSlot | None:
    """Byter ut receptet i en menyplats mot ett annat."""
    slot = db.query(MenuSlot).filter(MenuSlot.id == slot_id).first()
    if not slot:
        return None

    # Hämta alla recept-ID:n som redan är i menyn
    current_menu = db.query(MenuSlot).filter(
        MenuSlot.year == slot.year,
        MenuSlot.week_number == slot.week_number,
    ).all()
    used_ids = {s.recipe_id for s in current_menu}

    # Hämta deals-matchningar — bara middagskategorier
    matches = match_recipes_to_deals(db)
    matched_recipes = [m["recipe"] for m in matches
                       if m["recipe"].id not in used_ids
                       and m["recipe"].category in _MENU_CATEGORIES]

    # Alla övriga recept — bara middagskategorier
    all_recipes = db.query(Recipe).options(
        joinedload(Recipe.ratings),
    ).filter(Recipe.category.in_(_MENU_CATEGORIES)).all()
    other = [r for r in all_recipes
             if r.id not in used_ids and r.id not in {m.id for m in matched_recipes}]

    candidates = matched_recipes + other
    if not candidates:
        return slot

    # Försök hitta en annan kategori än nuvarande
    current_cat = slot.recipe.category if slot.recipe else None
    diff_cat = [r for r in candidates if r.category != current_cat]
    pool = diff_cat if diff_cat else candidates

    new_recipe = random.choice(pool)
    slot.recipe_id = new_recipe.id
    db.commit()
    db.refresh(slot)
    return slot


def update_slot_servings(db: Session, slot_id: int, servings: int) -> MenuSlot | None:
    slot = db.query(MenuSlot).filter(MenuSlot.id == slot_id).first()
    if slot:
        slot.servings = max(1, servings)
        db.commit()
        db.refresh(slot)
    return slot


def _pick_varied(candidates: list, count: int) -> list:
    """Väljer recept med spridning över kategorier."""
    selected = []
    used_categories = set()

    # Första pass: ett per kategori
    for recipe in candidates:
        if len(selected) >= count:
            break
        cat = recipe.category or "okategoriserad"
        if cat not in used_categories:
            selected.append(recipe)
            used_categories.add(cat)

    # Fyll på om vi inte har tillräckligt
    for recipe in candidates:
        if len(selected) >= count:
            break
        if recipe not in selected:
            selected.append(recipe)

    return selected


# --- Inköpslista ---

def get_shopping_list(db: Session, year: int = 0, week: int = 0) -> list[ShoppingItem]:
    now = datetime.now(timezone.utc)
    if not year:
        year = now.isocalendar()[0]
    if not week:
        week = now.isocalendar()[1]
    return db.query(ShoppingItem).filter(
        ShoppingItem.year == year,
        ShoppingItem.week_number == week,
    ).order_by(ShoppingItem.checked.desc(), ShoppingItem.name).all()


def add_recipe_to_shopping_list(db: Session, recipe_id: int, servings: int = 4) -> int:
    """Lägger till ett recepts ingredienser på inköpslistan. Returnerar antal tillagda."""
    recipe = db.query(Recipe).options(
        joinedload(Recipe.ingredients),
    ).filter(Recipe.id == recipe_id).first()
    if not recipe:
        return 0

    now = datetime.now(timezone.utc)
    year, week, _ = now.isocalendar()

    # Skalningsfaktor
    scale = servings / recipe.servings if recipe.servings else 1

    # Hämta befintliga items för denna vecka (för ihopslagning)
    existing_items = db.query(ShoppingItem).filter(
        ShoppingItem.year == year,
        ShoppingItem.week_number == week,
    ).all()
    existing_map = {}
    for item in existing_items:
        existing_map[item.name.lower().strip()] = item

    added = 0
    for ing in recipe.ingredients:
        if not ing.name.strip():
            continue
        quantity = _scale_quantity(ing.quantity or "", scale)
        ing_key = ing.name.lower().strip()

        # Försök slå ihop med befintlig
        if ing_key in existing_map:
            existing = existing_map[ing_key]
            merged = _merge_quantities(existing.quantity or "", quantity)
            if merged:
                existing.quantity = merged
                # Lägg till receptnamn om det inte redan finns
                if recipe.name not in (existing.recipe_name or ""):
                    existing.recipe_name = f"{existing.recipe_name}, {recipe.name}"
                added += 1
                continue

        item = ShoppingItem(
            name=ing.name,
            quantity=quantity,
            recipe_name=recipe.name,
            checked=1,
            week_number=week,
            year=year,
        )
        db.add(item)
        existing_map[ing_key] = item
        added += 1

    db.commit()
    return added


def toggle_shopping_item(db: Session, item_id: int) -> ShoppingItem | None:
    item = db.query(ShoppingItem).filter(ShoppingItem.id == item_id).first()
    if item:
        item.checked = 0 if item.checked else 1
        db.commit()
        db.refresh(item)
    return item


def clear_shopping_list(db: Session, year: int = 0, week: int = 0) -> int:
    now = datetime.now(timezone.utc)
    if not year:
        year = now.isocalendar()[0]
    if not week:
        week = now.isocalendar()[1]
    count = db.query(ShoppingItem).filter(
        ShoppingItem.year == year,
        ShoppingItem.week_number == week,
    ).delete()
    db.commit()
    return count


def remove_shopping_item(db: Session, item_id: int) -> bool:
    item = db.query(ShoppingItem).filter(ShoppingItem.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
        return True
    return False


def _scale_quantity(quantity: str, scale: float) -> str:
    """Skalar en mängdsträng med en faktor. Hanterar blandade bråk som '1 1/2'."""
    import re
    if not quantity or scale == 1:
        return quantity
    # Blandade bråk: "1 1/2 tsk" → 1.5
    m = re.match(r'^(\d+)\s+(\d+/\d+)\s*(.*)', quantity)
    if m:
        whole = float(m.group(1))
        frac_parts = m.group(2).split('/')
        val = whole + float(frac_parts[0]) / float(frac_parts[1])
        unit = m.group(3)
        return _format_scaled(val * scale, unit)
    # Enkla bråk: "1/2 tsk"
    m = re.match(r'^(\d+/\d+)\s*(.*)', quantity)
    if m:
        frac_parts = m.group(1).split('/')
        val = float(frac_parts[0]) / float(frac_parts[1])
        unit = m.group(2)
        return _format_scaled(val * scale, unit)
    # Vanliga tal: "500 g", "2,5 dl"
    m = re.match(r'^([\d.,]+)\s*(.*)', quantity)
    if m:
        try:
            val = float(m.group(1).replace(',', '.'))
            unit = m.group(2)
            return _format_scaled(val * scale, unit)
        except ValueError:
            pass
    return quantity


def _parse_quantity(qty: str) -> tuple[float | None, str]:
    """Parsar en mängdsträng till (tal, enhet). Returnerar (None, '') om det inte går."""
    import re
    if not qty:
        return None, ""
    qty = qty.strip()
    # Blandade bråk: "1 1/2 dl"
    m = re.match(r'^(\d+)\s+(\d+/\d+)\s*(.*)', qty)
    if m:
        parts = m.group(2).split('/')
        return float(m.group(1)) + float(parts[0]) / float(parts[1]), m.group(3).strip()
    # Bråk: "1/2 dl"
    m = re.match(r'^(\d+/\d+)\s*(.*)', qty)
    if m:
        parts = m.group(1).split('/')
        return float(parts[0]) / float(parts[1]), m.group(2).strip()
    # Vanligt tal: "500 g"
    m = re.match(r'^([\d.,]+)\s*(.*)', qty)
    if m:
        try:
            return float(m.group(1).replace(',', '.')), m.group(2).strip()
        except ValueError:
            pass
    return None, ""


def _merge_quantities(existing_qty: str, new_qty: str) -> str | None:
    """Slår ihop två mängder om de har samma enhet. Returnerar None om det inte går."""
    val1, unit1 = _parse_quantity(existing_qty)
    val2, unit2 = _parse_quantity(new_qty)

    if val1 is None or val2 is None:
        return None
    if unit1.lower() != unit2.lower():
        return None

    total = val1 + val2
    return _format_scaled(total, unit1)


def _format_scaled(val: float, unit: str) -> str:
    """Formaterar ett skalat värde snyggt."""
    if val == int(val):
        return f"{int(val)} {unit}".strip()
    # Visa som bråk om det är nära vanliga bråk
    frac_map = {0.25: "1/4", 0.5: "1/2", 0.75: "3/4", 0.33: "1/3", 0.67: "2/3"}
    whole = int(val)
    frac = val - whole
    for target, symbol in frac_map.items():
        if abs(frac - target) < 0.05:
            if whole:
                return f"{whole} {symbol} {unit}".strip()
            return f"{symbol} {unit}".strip()
    return f"{val:.1f} {unit}".strip().replace('.', ',')
