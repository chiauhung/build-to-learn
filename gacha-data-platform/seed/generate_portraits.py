"""
Generate 21 character portraits using Google Gemini API.
Saves as 384x512 WebP to portraits/{id}.webp
"""

import json
import os
from pathlib import Path
import io

from google import genai
from google.genai import types
from PIL import Image, ImageOps

# --- Config ---
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("Set GEMINI_API_KEY environment variable")

client = genai.Client(api_key=API_KEY)

PORTRAITS_DIR = Path(__file__).parent / "portraits"
CHARACTERS_JSON = Path(__file__).parent / "characters.json"

BASE_STYLE = (
    "genshin impact art style, anime illustration, bust shot portrait, "
    "clean gradient background, otome gacha card art, soft cel shading, "
    "detailed anime face, vibrant colors, Japanese RPG character design"
)


def generate_portrait(character: dict) -> None:
    char_id = character["id"]
    name = character["name"]
    prompt_hint = character["visual"]["prompt_hint"]
    output_path = PORTRAITS_DIR / f"{char_id}.webp"

    if output_path.exists():
        print(f"  [skip] {char_id} already exists")
        return

    full_prompt = f"{BASE_STYLE}, {prompt_hint}, character name: {name}"
    print(f"  [gen]  {char_id} — {name}")

    response = client.models.generate_content(
        model="gemini-3.1-flash-image-preview",
        contents=full_prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
        ),
    )

    img_data = None
    for part in response.candidates[0].content.parts:
        if part.inline_data is not None:
            img_data = part.inline_data.data
            break

    if img_data is None:
        print(f"  [err]  no image returned for {char_id}")
        return

    img = Image.open(io.BytesIO(img_data))
    img = ImageOps.fit(img, (384, 512), Image.LANCZOS)
    img.save(output_path, format="WEBP", quality=85)
    print(f"  [ok]   saved {output_path.name} ({output_path.stat().st_size // 1024}KB)")


def main():
    PORTRAITS_DIR.mkdir(exist_ok=True)

    with open(CHARACTERS_JSON) as f:
        data = json.load(f)

    characters = data["characters"]
    print(f"Generating {len(characters)} portraits...\n")

    for char in characters:
        generate_portrait(char)

    print("\nDone.")


if __name__ == "__main__":
    main()
