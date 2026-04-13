"""Bildverktyg: EXIF-rotation, komprimering."""
import io
from PIL import Image, ImageOps


def fix_orientation(image_data: bytes) -> bytes:
    """Läser EXIF-orientation och roterar bilden korrekt.
    Använder Pillows inbyggda exif_transpose för maximal kompatibilitet.
    Returnerar korrigerad JPEG-data."""
    try:
        img = Image.open(io.BytesIO(image_data))

        # Pillow's exif_transpose hanterar alla 8 EXIF-orientationer korrekt
        img = ImageOps.exif_transpose(img)

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
        return image_data
