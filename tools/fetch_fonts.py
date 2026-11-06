"""Download the portal's web fonts so they are served from our own domain.

Self-hosting means one fewer third-party connection, fonts that arrive with the page (they can be
preloaded), and no layout jump when a late font swaps in. Only the Latin, Latin-extended and
Ethiopic subsets are kept. Run from the portal folder:  python tools/fetch_fonts.py
Writes static/fonts/*.woff2 and static/fonts/fonts.css. Font licences: SIL Open Font License 1.1."""
import re
import urllib.request
from pathlib import Path

CSS_URL = ("https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500"
           "&family=Noto+Sans+Ethiopic:wght@400;600&family=Noto+Sans:wght@400;500;600;700"
           "&family=Zilla+Slab:wght@500;600;700&display=swap")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
KEEP = {"latin", "latin-ext", "ethiopic"}
OUT = Path(__file__).resolve().parent.parent / "static" / "fonts"


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60).read()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    css = get(CSS_URL).decode("utf-8")
    blocks = re.findall(r"/\*\s*([\w-]+)\s*\*/\s*(@font-face\s*{[^}]*})", css)
    saved, out = {}, ["/* Self-hosted by tools/fetch_fonts.py. SIL Open Font License 1.1. */"]
    for subset, block in blocks:
        if subset not in KEEP:
            continue
        family = re.search(r"font-family:\s*'([^']+)'", block).group(1)
        weight = re.search(r"font-weight:\s*(\d+)", block).group(1)
        url = re.search(r"url\((https://[^)]+)\)", block).group(1)
        if url not in saved:
            name = f"{family.lower().replace(' ', '-')}-{weight}-{subset}.woff2"
            (OUT / name).write_bytes(get(url))
            saved[url] = name
        out.append(f"/* {subset} */\n" + block.replace(url, saved[url]))
    (OUT / "fonts.css").write_text("\n".join(out) + "\n", encoding="utf-8")
    size = sum((OUT / n).stat().st_size for n in set(saved.values()))
    print(f"{len(set(saved.values()))} files, {size // 1024} KB")
    for n in sorted(set(saved.values())):
        print(" ", n)


if __name__ == "__main__":
    main()
