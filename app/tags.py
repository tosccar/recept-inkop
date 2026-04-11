"""Fördefinierade taggar och auto-suggest-logik."""

PREDEFINED_TAGS = [
    {"id": "vardag", "label": "Vardag", "description": "Vardagsmat"},
    {"id": "helg", "label": "Helg", "description": "Helgmat, lite mer avancerat"},
    {"id": "barnen", "label": "Barnen", "description": "Barnen kan laga själva"},
    {"id": "festmåltid", "label": "Festmåltid", "description": "Festlig mat"},
    {"id": "clean-protein", "label": "Clean protein", "description": "Mycket protein, måttligt med kolhydrater"},
]


def suggest_tags(title: str, ingredients: list[str], category: str) -> list[str]:
    """Föreslår taggar baserat på receptets innehåll."""
    tags = []
    all_text = (title + " " + " ".join(ingredients)).lower()
    num_ingredients = len(ingredients)

    # Filtrera bort "triviala" ingredienser vid räkning
    trivial = ["salt", "peppar", "olja", "olivolja", "vatten", "smör", "matolja",
               "svartpeppar", "matfett", "malen svartpeppar"]
    real_ingredients = [i for i in ingredients if i.lower().strip() not in trivial]
    num_real = len(real_ingredients)

    # --- Festmåltid ---
    fancy_words = ["entrecôte", "entrecote", "lammracks", "oxfilé", "hummer",
                   "tryffel", "saffran", "champagne", "fest", "julbord",
                   "kalvfond", "balsamvin", "parmesan", "timjan"]
    fancy_ingredients = ["oxfilé", "lammracks", "hummer", "tryffel",
                         "kalvfond", "champagne"]
    is_fancy = any(w in all_text for w in fancy_ingredients)

    if is_fancy or num_real > 15:
        tags.append("festmåltid")

    # --- Vardag vs Helg ---
    if is_fancy or num_real > 12:
        tags.append("helg")
    elif num_real <= 10:
        tags.append("vardag")

    # --- Barnen ---
    complex_words = ["marinera", "degblandning", "jäs", "flambera",
                     "reducera", "sous vide", "fritera", "filera"]
    is_complex = any(w in all_text for w in complex_words)
    if num_real <= 7 and not is_complex:
        tags.append("barnen")

    # --- Clean protein ---
    protein_sources = ["kyckling", "kycklingfilé", "kycklingbröst", "lax",
                       "torsk", "räk", "tonfisk", "kalkon", "biff", "oxfilé",
                       "ägg", "cottage cheese", "kvarg", "tofu"]
    heavy_carbs = ["pasta", "spagetti", "penne", "ris", "potatis", "bröd",
                   "tortilla", "couscous", "bulgur", "nudl", "gnocchi"]
    heavy_fat = ["grädde", "crème fraiche", "creme fraiche", "smör",
                 "panerad", "friterad", "ost", "bacon"]

    has_protein = any(w in all_text for w in protein_sources)
    has_heavy_carbs = any(w in all_text for w in heavy_carbs)
    has_heavy_fat = any(w in all_text for w in heavy_fat)

    if has_protein and not has_heavy_carbs and not has_heavy_fat:
        tags.append("clean-protein")

    return tags
