"""Map design font_family names to ASS Fontname strings (match bundled TTF internal names)."""

from __future__ import annotations

# Lowercase key -> family name as recognized by libass for our bundled files
FAMILY_TO_ASS_NAME: dict[str, str] = {
    "montserrat": "Montserrat",
    "poppins": "Poppins",
    "inter": "Inter",
    "oswald": "Oswald",
    "anton": "Anton",
    "bebas neue": "Bebas Neue",
    "bangers": "Bangers",
    "arial": "Arial",
}


def ass_font_name(family: str) -> str:
    key = (family or "Arial").strip().lower()
    return FAMILY_TO_ASS_NAME.get(key, family.strip() or "Arial")
