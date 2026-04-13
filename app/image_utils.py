"""Bildverktyg: EXIF-rotation, komprimering."""
import io
from PIL import Image, ExifTags


def fix_orientation(image_data: bytes) -> bytes:
    """Läser EXIF-orientation och roterar bilden korrekt.
    Returnerar korrigerad JPEG-data."""
    try:
        img = Image.open(io.BytesIO(image_data))

        # Hitta EXIF-orientation
        exif = img.getexif()
        orientation_key = None
        for key, val in ExifTags.TAGS.items():
            if val == "Orientation":
                orientation_key = key
                break

        if orientation_key and orientation_key in exif:
            orientation = exif[orientation_key]
            if orientation == 3:
                img = img.rotate(180, expand=True)
            elif orientation == 6:
                img = img.rotate(270, expand=True)
            elif orientation == 8:
                img = img.rotate(90, expand=True)

        # Konvertera RGBA till RGB om nödvändigt
        if img.mode == "RGBA":
            img = img.convert("RGB")

        # Begränsa storlek (max 1600px bred/hög)
        max_dim = 1600
        if img.width > max_dim or img.height > max_dim:
            img.thumbnail((max_dim, max_dim), Image.LANCZOS)

        # Spara som JPEG utan EXIF (rotation redan applicerad)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()

    except Exception:
        # Om något går fel, returnera originaldata
        return image_data
