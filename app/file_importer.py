"""Importerar recept från filer (PDF, Word, bilder, text)."""
import os
import re
import subprocess
import logging
from pathlib import Path

import fitz  # PyMuPDF
from docx import Document
from fpdf import FPDF

logger = logging.getLogger(__name__)

# Mappnamn → kategori
_FOLDER_CATEGORY_MAP = {
    "bröd": "kakor/tårtor",
    "dryck": "dryck",
    "efterrätt": "efterrätt",
    "efterrätter": "efterrätt",
    "fisk": "fisk",
    "förrätt": "förrätt",
    "gröt": "övrigt",
    "kakor": "kakor/tårtor",
    "kyckling": "kyckling",
    "kött ox, lamm och gris": "kött",
    "matpaj": "övrigt",
    "pasta": "pasta",
    "soppa": "soppa",
    "sås": "övrigt",
    "tårta": "kakor/tårtor",
    "vegetariskt": "vegetariskt",
}


def extract_text_from_file(filepath: str) -> str:
    """Extraherar text från en fil baserat på filtyp."""
    ext = Path(filepath).suffix.lower()

    if ext == ".pdf":
        return _extract_pdf(filepath)
    elif ext == ".docx":
        return _extract_docx(filepath)
    elif ext == ".doc":
        return _extract_doc(filepath)
    elif ext == ".txt":
        return _extract_txt(filepath)
    elif ext in (".jpg", ".jpeg", ".png"):
        return None  # Kräver bildanalys
    else:
        return None


def _extract_pdf(filepath: str) -> str:
    """Extraherar text från PDF med PyMuPDF."""
    try:
        doc = fitz.open(filepath)
        text = ""
        for page in doc:
            text += page.get_text() + "\n"
        doc.close()
        text = text.strip()
        if len(text) < 20:
            return None  # Bildbaserad PDF, behöver OCR
        return text
    except Exception as e:
        logger.error(f"PDF-fel {filepath}: {e}")
        return None


def _extract_docx(filepath: str) -> str:
    """Extraherar text från .docx."""
    try:
        doc = Document(filepath)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        logger.error(f"DOCX-fel {filepath}: {e}")
        return None


def _extract_doc(filepath: str) -> str:
    """Extraherar text från .doc via antiword."""
    try:
        result = subprocess.run(
            ["antiword", filepath],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return None
    except Exception as e:
        logger.error(f"DOC-fel {filepath}: {e}")
        return None


def _extract_txt(filepath: str) -> str:
    """Läser textfil."""
    try:
        for enc in ("utf-8", "latin-1", "cp1252"):
            try:
                return Path(filepath).read_text(encoding=enc).strip()
            except UnicodeDecodeError:
                continue
        return None
    except Exception as e:
        logger.error(f"TXT-fel {filepath}: {e}")
        return None


def convert_to_pdf(filepath: str, output_dir: str) -> str | None:
    """Konverterar en Word/text-fil till PDF. Returnerar PDF-sökväg."""
    ext = Path(filepath).suffix.lower()
    if ext == ".pdf":
        return filepath  # Redan PDF

    # Läs innehåll
    if ext == ".docx":
        text = _extract_docx(filepath)
    elif ext == ".doc":
        text = _extract_doc(filepath)
    elif ext == ".txt":
        text = _extract_txt(filepath)
    else:
        return None

    if not text:
        return None

    # Skapa PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    # Titel från filnamn
    title = get_recipe_name_from_file(filepath)
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, _pdf_clean(title), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Innehåll
    pdf.set_font("Helvetica", "", 11)
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            pdf.ln(4)
            continue
        cleaned = _pdf_clean(line)
        # Bryt för långa ord som inte får plats
        if len(cleaned) > 80:
            cleaned = cleaned[:200]
        try:
            pdf.multi_cell(0, 6, cleaned)
        except Exception:
            pass

    safe_name = re.sub(r'[^\w\s\-]', '', title).strip().replace(' ', '_')[:60]
    out_path = os.path.join(output_dir, f"{safe_name}.pdf")
    pdf.output(out_path)
    return out_path


def _pdf_clean(text: str) -> str:
    """Rensar text för PDF-rendering."""
    replacements = {
        '\u2013': '-', '\u2014': '-', '\u2018': "'", '\u2019': "'",
        '\u201c': '"', '\u201d': '"', '\u2026': '...', '\u00bd': '1/2',
        '\u00bc': '1/4', '\u00be': '3/4',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.encode('latin-1', errors='replace').decode('latin-1')


def guess_category_from_folder(filepath: str) -> str:
    """Gissar kategori baserat på mappnamn."""
    parent = Path(filepath).parent.name.lower()
    return _FOLDER_CATEGORY_MAP.get(parent, "")


def get_recipe_name_from_file(filepath: str) -> str:
    """Gissar receptnamn från filnamn."""
    name = Path(filepath).stem
    # Rensa bort vanliga suffix
    name = re.sub(r'\s*[-_]\s*Recept.*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s*_ Recept.*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s*\(Konflikt.*\)$', '', name)
    name = re.sub(r'\s*[-_]\s*mat och vin.*$', '', name, flags=re.IGNORECASE)
    # Ta bort datumprefix typ "2020-09-23 16.18.46"
    name = re.sub(r'^\d{4}-\d{2}-\d{2}\s+\d{2}\.\d{2}\.\d{2}$', '', name)
    return name.strip() or Path(filepath).stem
