#!/usr/bin/env python3
"""Download the design's fonts (Geist 400-600, Geist Mono 400-500) from Google Fonts into fonts/ for self-hosting.

Google's CSS2 API serves each family as one variable woff2 per character subset; SUBSETS of them are saved, and
fonts/fonts.json records each file's family, weight range, unicode-range, source URL and sha256 so build.py can
write the @font-face rules. Both families are under the SIL Open Font License 1.1 (fonts/OFL.txt).
Standard library only. Runs from the IDE Run button.
"""
import hashlib
import json
from pathlib import Path
import re
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "fonts"
CSS_URL = ("https://fonts.googleapis.com/css2?family=Geist:wght@400..600&family=Geist+Mono:wght@400..500"
           "&display=swap")
SUBSETS = ("latin", "latin-ext")
PRELOAD = {"latin"}  # subsets every page needs: preloaded; the others download only when a glyph needs them
# Google picks the font format from the User-Agent; a current desktop browser gets woff2.
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
FACE = re.compile(r"/\*\s*([\w-]+)\s*\*/\s*@font-face\s*{([^}]*)}")


def get(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main():
    css = get(CSS_URL).decode()
    FONTS.mkdir(exist_ok=True)
    faces = []
    for subset, body in FACE.findall(css):
        if subset not in SUBSETS:
            continue
        field = lambda name: re.search(rf"{name}:\s*([^;]+);", body).group(1).strip()  # noqa: E731
        family = field("font-family").strip("'\"")
        url = re.search(r"url\(([^)]+)\)\s*format\('woff2'\)", field("src")).group(1)
        data = get(url)
        if data[:4] != b"wOF2":
            raise RuntimeError(f"{url} is not woff2")
        name = f"{family.lower().replace(' ', '-')}-{subset}.woff2"
        (FONTS / name).write_bytes(data)
        faces.append({"family": family, "subset": subset, "file": name, "weight": field("font-weight"),
                      "unicode_range": field("unicode-range"), "preload": subset in PRELOAD, "source": url,
                      "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
        print(f"{name}: {len(data):,} bytes, weight {faces[-1]['weight']}, from {url}")
    found = {(face["family"], face["subset"]) for face in faces}
    missing = [(family, subset) for family in ("Geist", "Geist Mono") for subset in SUBSETS if (family, subset) not in found]
    if missing:
        raise RuntimeError(f"Google Fonts CSS lacks {missing}")
    (FONTS / "fonts.json").write_text(json.dumps({"css": CSS_URL, "faces": faces}, indent=1) + "\n")


if __name__ == "__main__":
    main()
