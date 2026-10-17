"""List every phrase the page can show, as the patterns the translations are keyed by.

The page translates what it shows by whole phrases and by patterns with numbered holes
("{0} moves {1} regiments from {2} to {3}"; see web/i18n.js). This finds them in the sources:
the page's scripts and HTML (template literals, with each ${...} a hole and each tag a break),
the engine's f-strings (event summaries, refusals), the fortune events' texts, and the names in
the static data. It prints the ones the given dictionary lacks, or writes them all:

    uv run python scripts/i18n_extract.py --missing es     # what es.json does not translate yet
    uv run python scripts/i18n_extract.py --all > /tmp/all.json
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "src" / "pax_agentica"
WEB = PKG / "web"
LETTERS = re.compile(r"[A-Za-z]{3}")
CSS = re.compile(r"[{}]|=>|\$\(|\bvar\(|\bpx\b|rgba?\(|#[0-9a-f]{3}|\b[a-z-]+:\s*[^;\s]+;")
CODE = re.compile(r"^[a-z0-9_\-./#:;=()\[\]{}\s]*$")  # identifiers, classes, CSS, paths


def keep(s: str) -> bool:
    """A phrase a player reads, not a class name, a key or a piece of CSS."""
    s = s.strip()
    literal = re.sub(r"\{\d+\}", "", s)
    if not LETTERS.search(literal):
        return False
    if CODE.match(s) and " " not in s.strip():  # one lowercase token: a key or a class
        return False
    if CSS.search(literal):
        return False
    return not s.startswith(("http", "/", "M", "data:")) or (" " in s and not s.startswith("M"))


def tidy(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    # renumber the holes in the order they come
    n = iter(range(100))
    return re.sub(r"\{\d+\}", lambda _: f"{{{next(n)}}}", s)


# ---------------------------------------------------------------- JavaScript and HTML
def templates(js: str) -> list[str]:
    """Each template literal's text, ${...} as holes, nested templates on their own."""
    out: list[str] = []

    def scan(i: int) -> tuple[str, int]:  # from just after a backtick to just after its close
        text, holes = "", 0
        while i < len(js):
            c = js[i]
            if c == "\\":
                text += js[i : i + 2]
                i += 2
            elif c == "`":
                return text, i + 1
            elif js.startswith("${", i):
                depth, j = 1, i + 2
                while j < len(js) and depth:
                    if js[j] == "`":
                        inner, j = scan(j + 1)
                        out.append(inner)
                        continue
                    if js[j] in "'\"":
                        q = js[j]
                        j += 1
                        while j < len(js) and js[j] != q:
                            j += 2 if js[j] == "\\" else 1
                    depth += js[j] == "{"
                    depth -= js[j] == "}"
                    j += 1
                text += f"{{{holes}}}"
                holes += 1
                i = j
            else:
                text += c
                i += 1
        return text, i

    i = 0
    while i < len(js):
        if js.startswith("//", i):
            i = js.find("\n", i)
            if i < 0:
                break
        elif js[i] == "`":
            text, i = scan(i + 1)
            out.append(text)
        else:
            i += 1
    return out


def strings(js: str) -> list[str]:
    no_templates = re.sub(r"`(?:\\.|[^`\\])*`", "``", js)
    no_comments = re.sub(r"//[^\n]*", "", no_templates)
    return [m.group(2) for m in re.finditer(r"(['\"])((?:\\.|(?!\1).)*)\1", no_comments)]


def pieces(text: str) -> list[str]:
    """A template's text split at its tags and attributes: what each text node will hold."""
    found: list[str] = []
    for attr in re.findall(r'(?:title|aria-label|placeholder|alt|data-tip)="([^"]*)"', text):
        found.extend(pieces(attr.replace("&lt;", "<").replace("&gt;", ">")))
    for chunk in re.split(r"<[^>]*>", text):
        chunk = chunk.replace("&amp;", "&").replace("&nbsp;", " ").replace("&ensp;", " ")
        if keep(chunk):
            found.append(tidy(chunk))
    return found


class Html(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.found: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self.skip += 1
        for k, v in attrs:
            if k in ("title", "aria-label", "placeholder", "alt", "data-tip") and v and keep(v):
                self.found.extend(pieces(v))

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self.skip -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip and keep(data):
            self.found.append(tidy(data))


def from_web() -> set[str]:
    found: set[str] = set()
    for name in ("play.js", "map.js", "juice.js", "scenes.js"):
        js = (WEB / name).read_text(encoding="utf-8")
        for text in templates(js):
            found.update(pieces(text))
        prose = [s for s in strings(js) if (keep(s) and " " in s.strip()) or s[:1].isupper()]
        found.update(tidy(s) for s in prose)
    for name in ("play.html", "lobby.html"):
        page = (WEB / name).read_text(encoding="utf-8")
        parser = Html()
        parser.feed(page)
        found.update(parser.found)
        for script in re.findall(r"<script>(.*?)</script>", page, re.S):
            for text in templates(script):
                found.update(pieces(text))
    return {f for f in found if keep(f)}


# ---------------------------------------------------------------- Python
def fstring(node: ast.JoinedStr) -> str:
    text, holes = "", 0
    for part in node.values:
        if isinstance(part, ast.Constant):
            text += str(part.value)
        else:
            text += f"{{{holes}}}"
            holes += 1
    return text


def from_python() -> set[str]:
    found: set[str] = set()
    files = [
        *sorted((PKG / "engine").glob("*.py")),
        *sorted((PKG / "players").glob("*.py")),  # the bots' letters and proclamations
        PKG / "viewer.py",
        PKG / "server.py",
        PKG / "multiplayer.py",
    ]
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            id(n.body[0].value)
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module))
            and n.body
            and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                s = fstring(node)
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                s = re.sub(r"\{\w+\}", "{0}", node.value)  # str.format holes (the fortune texts)
            else:
                continue
            if " " in s.strip() and keep(s):
                found.add(tidy(s))
    return found


def from_data() -> set[str]:
    """Every name and line in the static data the page receives."""
    from pax_agentica.engine import new_game
    from pax_agentica.viewer import europe_map, static_payload

    found: set[str] = set()

    def walk(v: Any) -> None:
        if isinstance(v, str):
            wanted = (keep(v) and not v.startswith(("M", "m "))) or (
                v[:1].isupper() and len(v) < 40
            )
            if wanted and not re.match(r"^[MLHVCSQTAZ0-9.\-\s,]+$", v):  # not an SVG path
                found.add(tidy(v))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)

    static = static_payload(new_game(1), europe_map())
    for key, value in static.items():
        if key not in ("map",):
            walk(value)
    return {f for f in found if len(f) < 600}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--missing", metavar="LANG")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    found = from_web() | from_python() | from_data()
    if args.missing:
        known = json.loads((WEB / "i18n" / f"{args.missing}.json").read_text(encoding="utf-8"))
        found = {f for f in found if f not in known}
    print(json.dumps(sorted(found), indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
