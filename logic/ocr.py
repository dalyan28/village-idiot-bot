import pytesseract
from PIL import Image
import aiohttp
import io
import json


CHARACTERS_FILE = "characters.json"


def load_characters() -> dict:
    with open(CHARACTERS_FILE, "r") as f:
        return json.load(f)


TYPE_PRIORITY = {
    "demon": 4,
    "minion": 3,
    "outsider": 2,
    "townsfolk": 1,
}


async def download_image(url: str) -> Image.Image:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.read()
            return Image.open(io.BytesIO(data))


def extract_characters(image: Image.Image, characters: dict) -> list[str]:
    text = pytesseract.image_to_string(image)
    found = []
    for name in characters:
        if name.lower() in text.lower():
            found.append(name)
    return found


def get_top4(found: list[str], characters: dict) -> list[dict]:
    import random

    scored = [
        {
            "name": name,
            "score": characters[name]["score"],
            "type": characters[name]["type"],
            "priority": TYPE_PRIORITY[characters[name]["type"]],
        }
        for name in found if name in characters
    ]

    scored.sort(key=lambda x: (x["score"], x["priority"], random.random()), reverse=True)

    return scored[:4]


def format_top4(top4: list[dict]) -> str:
    if not top4:
        return ""
    parts = []
    for c in top4:
        if c["score"] >= 9:
            parts.append(f"🔹**{c['name']}**")
        else:
            parts.append(f"*{c['name']}*")
    return " · ".join(parts)


async def analyse_attachment(url: str, characters: dict) -> list[str]:
    image = await download_image(url)
    return extract_characters(image, characters)