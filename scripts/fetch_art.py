"""Fetch the game's period art from Wikimedia Commons, crop it, and write its credits.

Every image is a painting, print or engraving that Commons marks as public domain (or CC0),
taken at a thumbnail size, cropped around a focal point and saved as JPEG next to the page:

    web/scenes/  the scenes of the age (battles, sieges, treaties, the news of the year), 760x300
    web/faces/   anonymous portraits of the period, for people with no painting of their own,
                 160x200
    web/views/   town views for provinces with none of their own, 570x225

Run it again after changing the lists below; it keeps a cache of what it downloaded:

    uv run --with pillow python scripts/fetch_art.py --cache /tmp/pax-art
"""

from __future__ import annotations

import argparse
import html
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

WEB = Path(__file__).resolve().parent.parent / "src" / "pax_agentica" / "web"
UA = {"User-Agent": "PaxAgentica/0.1 (game art; public-domain credits kept in the repository)"}
FREE = ("Public domain", "PD", "CC0", "PDM")


@dataclass(frozen=True)
class Art:
    id: str
    file: str  # the title on Commons, without "File:"
    fx: float = 0.5  # the focal point, as fractions of the width and height
    fy: float = 0.5
    zoom: float = 1.0  # how much of the widest crop to keep
    label: str = ""  # scenes: what it shows; towns: the city; faces: the pool


SIZE = {"scenes": (760, 300), "faces": (160, 200), "views": (570, 225)}

SCENES = [
    Art(
        "battle-pavia",
        "Battle of Pavia, 1525 (by anonymous Flemish artist).jpg",
        0.5,
        0.55,
        0.8,
        "The Battle of Pavia",
    ),
    Art(
        "battle-orsha",
        "Autor nieznany (malarz z kręgu Lukasa Cranacha Starszego), Bitwa pod Orszą.jpg",
        0.5,
        0.62,
        0.7,
        "The Battle of Orsha",
    ),
    Art(
        "siege",
        "The Siege of Malta- Siege and Bombardment of Saint Elmo, 27 May 1565 RMG L9744.jpg",
        0.5,
        0.5,
        1,
        "The Siege of Malta",
    ),
    Art(
        "treaty",
        "The Ratification of the Treaty of Munster, Gerard Ter Borch (1648).jpg",
        0.5,
        0.52,
        1,
        "The Ratification of the Treaty of Münster",
    ),
    Art(
        "triumph",
        "Titian - Emperor Charles V at Mühlberg - WGA22965.jpg",
        0.5,
        0.3,
        1,
        "Emperor Charles V at Mühlberg",
    ),
    Art(
        "plague",
        "Pieter Bruegel the Elder - The Triumph of Death - WGA3389.jpg",
        0.5,
        0.5,
        1,
        "The Triumph of Death",
    ),
    Art(
        "frost",
        "Pieter Bruegel the Elder - The Hunters in the Snow (January) - WGA3434.jpg",
        0.5,
        0.45,
        1,
        "The Hunters in the Snow",
    ),
    Art(
        "fleet",
        "The Return to Amsterdam of the Second Expedition to the East Indies on 19 July 1599.jpg",
        0.5,
        0.5,
        1,
        "The Return of the Second Expedition",
    ),
    Art("reformation", "Luther95theses.jpg", 0.5, 0.5, 1, "Luther posts his theses"),
    Art(
        "harvest",
        "Pieter Bruegel the Elder- The Harvesters - Google Art Project (cropped).jpg",
        0.5,
        0.55,
        1,
        "The Harvesters",
    ),
    Art(
        "money",
        "Quinten Massijs (I) - The Moneylender and his Wife (detail) - WGA14282.jpg",
        0.5,
        0.5,
        1,
        "The Moneylender and his Wife",
    ),
    Art(
        "painter",
        "Jan Vermeer - The Art of Painting - Google Art Project.jpg",
        0.5,
        0.42,
        1,
        "The Art of Painting",
    ),
    Art("revolt", "Rudolf Schiestl Bauernhaufen 1525.jpg", 0.5, 0.5, 1, "Peasants' band, 1525"),
    Art("comet", "Great comet 1577.jpg", 0.5, 0.4, 1, "The Great Comet of 1577"),
    Art(
        "drill",
        "Rembrandt Harmensz. van Rijn - Nachtwacht - Google Art Project.jpg",
        0.5,
        0.55,
        1,
        "The Night Watch",
    ),
    Art(
        "court",
        "British - Field of the Cloth of Gold - Google Art Project.jpg",
        0.45,
        0.5,
        0.8,
        "The Field of the Cloth of Gold",
    ),
    Art(
        "fair",
        "Pieter Brueghel (II) - Fair with a theatrical presentation.jpg",
        0.5,
        0.55,
        1,
        "Fair with a theatrical presentation",
    ),
    Art("mine", "Annaberger-Bergaltar2 (cropped).jpg", 0.5, 0.5, 1, "The Annaberg miners' altar"),
    Art(
        "sea-lepanto",
        "Battle of Lepanto, 1571 (by Andrea Vicentino) - Doge's Palace, Venice (2).jpg",
        0.5,
        0.5,
        0.8,
        "The Battle of Lepanto",
    ),
    Art(
        "sea-armada",
        "English Ships and the Spanish Armada, August 1588 RMG BHC0262.jpg",
        0.5,
        0.5,
        0.9,
        "English Ships and the Spanish Armada",
    ),
    Art(
        "colony",
        "Jan Mostaert - Landscape with a Scene of the Conquest of America.jpg",
        0.5,
        0.55,
        1,
        "A Scene of the Conquest of America",
    ),
    Art(
        "landfall",
        "Columbus landing on Hispaniola.JPG",
        0.5,
        0.45,
        1,
        "Columbus lands on Hispaniola",
    ),
]

FACES = [
    Art(
        "man-1",
        "Hans Holbein d. J. - Portrait of a Man Holding Gloves and Letter - WGA11575.jpg",
        0.5,
        0.3,
        0.7,
        "man",
    ),
    Art("man-2", "Hans Holbein d. Ä. - Portrait of a Man - WGA11480.jpg", 0.5, 0.32, 0.7, "man"),
    Art(
        "man-3",
        "Ambrosius Holbein - Portrait of a Young Man - WGA11473.jpg",
        0.43,
        0.5,
        0.42,
        "man",
    ),
    Art("man-4", "Lorenzo Lotto - Portrait of a Man - WGA13657.jpg", 0.5, 0.32, 0.7, "man"),
    Art("man-5", "Hans Memling - Portrait of a Man - WGA14862.jpg", 0.5, 0.35, 0.75, "man"),
    Art(
        "man-6",
        "Hans Memling - Portrait of a Young Man before a Landscape - WGA14912.jpg",
        0.5,
        0.35,
        0.75,
        "man",
    ),
    Art(
        "man-7",
        "Giovanni Battista Moroni - Portrait of a Gentleman with a Dog - Walters 37501.jpg",
        0.5,
        0.3,
        0.6,
        "man",
    ),
    Art("man-8", "Giovanni Battista Moroni 008.jpg", 0.51, 0.2, 0.3, "man"),
    Art("man-9", "Domenico Ghirlandaio - Portrait of a Man.jpg", 0.5, 0.35, 0.7, "man"),
    Art("old-1", "Hans Memling - Portrait of an Old Man - WGA14851.jpg", 0.5, 0.35, 0.75, "old"),
    Art(
        "old-2",
        "Ridolfo del Ghirlandaio - Portrait of an Old Man - WGA08924.jpg",
        0.5,
        0.32,
        0.7,
        "old",
    ),
    Art(
        "woman-1",
        "Lucas Cranach d. Ä. - Portrait of a Woman - WGA05679.jpg",
        0.5,
        0.3,
        0.7,
        "woman",
    ),
    Art(
        "woman-2",
        "Hans Holbein d. J. - Portrait of Lady Mary Guildford - WGA11594.jpg",
        0.5,
        0.3,
        0.7,
        "woman",
    ),
    Art(
        "woman-3",
        "Lady with a Squirrel by Hans Holbein the Younger in the National Gallery.jpg",
        0.5,
        0.3,
        0.7,
        "woman",
    ),
    Art("man-10", "Titian - Portrait of a Man in a Red Cap - WGA22937.jpg", 0.5, 0.32, 0.7, "man"),
    Art("man-11", "Albrecht Dürer - Portrait of a Young Man - WGA06980.jpg", 0.5, 0.35, 0.8, "man"),
    Art(
        "man-12",
        "Lucas Cranach d. Ä. - Portrait of a Young Man - WGA05698.jpg",
        0.5,
        0.3,
        0.7,
        "man",
    ),
    Art("man-13", "Titian - Portrait of a Man with a Palm - WGA22977.jpg", 0.48, 0.22, 0.45, "man"),
    Art("man-14", "Albrecht Dürer - Portrait of a Man - WGA6957.jpg", 0.5, 0.35, 0.8, "man"),
    Art("old-3", "Cranach the Younger Portrait of a bearded man.jpg", 0.5, 0.32, 0.7, "old"),
    Art(
        "ottoman-1",
        "Aiax Aga, Pasha of Greece, a cavalry commander of Suleyman I. Portrait. 1540-1552.jpg",
        0.5,
        0.28,
        0.7,
        "ottoman",
    ),
    Art("ottoman-2", "Barbarossa Hayreddin Pasha.jpg", 0.5, 0.3, 0.7, "ottoman"),
    Art(
        "ottoman-3",
        "Ottoman Dynasty, Portrait of a Painter, Reign of Mehmet II (1444-1481).jpg",
        0.6,
        0.22,
        0.6,
        "ottoman",
    ),
    Art(
        "russian-1",
        "Hryhorii Hamaliia (Portrait, 2half 17th century).jpg",
        0.5,
        0.3,
        0.7,
        "russian",
    ),
    Art("russian-2", "Feodor III - parsuna near 1680.jpg", 0.5, 0.3, 0.7, "russian"),
    Art(
        "russian-3",
        "Feodor I of Russia (parsuna, 1630s, Moscow History museum).jpg",
        0.5,
        0.3,
        0.7,
        "russian",
    ),
]

VIEWS: list[Art] = []  # filled from towns.json below, one per province without a view


def api(params: dict[str, Any]) -> dict[str, Any]:
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(
        {"format": "json", **params}
    )
    return json.loads(fetch(url))


def fetch(url: str) -> bytes:
    for attempt in range(8):
        try:
            time.sleep(4)  # Commons asks for patience
            request = urllib.request.Request(url, headers=UA)  # noqa: S310 (https to Commons)
            return urllib.request.urlopen(request, timeout=60).read()  # noqa: S310
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(30 * (attempt + 1))
    raise RuntimeError(f"Commons keeps refusing: {url}")


def plain(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", value))).strip()


def info(art: Art, width: int) -> dict[str, Any]:
    r = api({"action": "query", "titles": f"File:{art.file}", "prop": "imageinfo",
             "iiprop": "url|size|extmetadata", "iiurlwidth": width,
             "iiextmetadatafilter": "LicenseShortName|Artist|DateTimeOriginal"})  # fmt: skip
    page = next(iter(r["query"]["pages"].values()))
    if "imageinfo" not in page:
        raise SystemExit(f"not on Commons: {art.file}")
    ii = page["imageinfo"][0]
    meta = {k: plain(v["value"]) for k, v in ii.get("extmetadata", {}).items()}
    licence = meta.get("LicenseShortName", "")
    if not licence.startswith(FREE):
        raise SystemExit(f"not public domain ({licence}): {art.file}")
    return {"thumb": ii.get("thumburl") or ii["url"], "page": ii["descriptionurl"],
            "licence": licence, "artist": meta.get("Artist", "unknown")[:80],
            "date": meta.get("DateTimeOriginal", "")[:40]}  # fmt: skip


def crop(img: Image.Image, art: Art, size: tuple[int, int]) -> Image.Image:
    w, h = img.size
    aspect = size[0] / size[1]
    cw = min(w, h * aspect) * art.zoom
    ch = cw / aspect
    x = min(max(0, art.fx * w - cw / 2), w - cw)
    y = min(max(0, art.fy * h - ch / 2), h - ch)
    return img.crop((round(x), round(y), round(x + cw), round(y + ch))).resize(
        size, Image.Resampling.LANCZOS
    )


def run(folder: str, arts: list[Art], cache: Path) -> list[dict[str, Any]]:
    out = WEB / folder
    out.mkdir(exist_ok=True)
    size = SIZE[folder]
    rows = []
    for art in arts:
        meta_path = cache / f"{folder}-{art.id}.json"
        raw_path = cache / f"{folder}-{art.id}.img"
        if (
            meta_path.exists()
            and raw_path.exists()
            and json.loads(meta_path.read_text())["file"] == art.file
        ):
            meta = json.loads(meta_path.read_text())
        else:
            try:
                meta = info(art, 960 if folder == "faces" else 1920)  # widths Commons keeps ready
                meta["file"] = art.file
                raw_path.write_bytes(fetch(meta["thumb"]))
            except RuntimeError as refused:  # the others still come; run it again for this one
                print(f"skipped {folder}/{art.id}: {refused}")
                continue
            meta_path.write_text(json.dumps(meta))
        img = Image.open(io.BytesIO(raw_path.read_bytes())).convert("RGB")
        img.info.clear()  # no museum captions or camera data inside the files we ship
        crop(img, art, size).save(
            out / f"{art.id}.jpg", quality=84, optimize=True, progressive=True
        )
        rows.append({"id": art.id, "label": art.label, **meta})
        print(f"{folder}/{art.id}.jpg  <- {art.file}")
    return rows


def link(row: dict[str, Any]) -> str:
    return f"[{row['file']}]({row['page']})"


def credit(row: dict[str, Any], name: str) -> str:
    cells = [name, row["label"], row["artist"], row["date"], row["licence"], link(row)]
    return "| " + " | ".join(cells) + " |"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--only", choices=sorted(SIZE), action="append")
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    towns = Path(__file__).with_name("towns.json")
    if towns.exists():
        VIEWS.extend(Art(**t) for t in json.loads(towns.read_text(encoding="utf-8")))
    for folder, arts in (("scenes", SCENES), ("faces", FACES), ("views", VIEWS)):
        if (args.only and folder not in args.only) or not arts:
            continue
        rows = run(folder, arts, args.cache)
        if folder == "views":
            write_views(rows)
            continue
        index = {r["id"]: {"label": r["label"], "by": r["artist"]} for r in rows}
        (WEB / folder / "index.json").write_text(
            json.dumps(index, indent=1, ensure_ascii=False) + "\n"
        )
        what = "Scenes of the age" if folder == "scenes" else "Faces of the age"
        lines = [f"# {what}", "",
                 "Paintings, prints and engravings in the **public domain** (Commons' own",
                 "licence statement below), from Wikimedia Commons, cropped by",
                 "`scripts/fetch_art.py`.", "",
                 "| File | Shows | Artist | Date | Licence | Source |",
                 "|---|---|---|---|---|---|"]  # fmt: skip
        lines += [credit(r, f"{r['id']}.jpg") for r in rows]
        (WEB / folder / "CREDITS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_views(rows: list[dict[str, Any]]) -> None:
    """Add the new town views to the views' index and credits, beside the ones already there."""
    index_path = WEB / "views" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    credits = (WEB / "views" / "CREDITS.md").read_text(encoding="utf-8").rstrip("\n").split("\n")
    for r in rows:
        by = (
            "Braun and Hogenberg"
            if re.search(r"Braun|Hogenberg", r["artist"] + r["file"])
            else r["artist"]
        )
        index[r["id"]] = {"city": r["label"], "by": by}
        credits = [c for c in credits if not c.startswith(f"| {r['id']} |")]
        credits.append(credit(r, r["id"]))
    index_path.write_text(json.dumps(index, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (WEB / "views" / "CREDITS.md").write_text("\n".join(credits) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
