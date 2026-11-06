"""Download openly licensed Wikimedia Commons photos at web sizes and write credits.

Usage: python tools/fetch_images.py
Writes static/img/<slug>-1600.jpg, <slug>-800.jpg and data/media.json.
"""
import json
import re
import shutil
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / "static" / "img"
UA = {"User-Agent": "BatuCityPortalDemo/0.1 (city portal prototype; image credits kept)"}

# slug -> (Commons file name, short caption)
COMMONS = {
    "lake-ziway-2017": ("Lake Ziway, January 2017.jpg", "Lake Dambal from the shore at Batu"),
    "lac-zway": ("Lac Zway.JPG", "Boats on Lake Dambal"),
    "lake-ziway-2008": ("Lake Ziway.jpg", "Lake Dambal"),
    "lake-ziway-wharf": ("Lake Ziway Wharf (11398504093).jpg", "The jetty at Batu"),
    "horses-lake-ziway": ("Horses at Lake Ziway (51233635510).jpg", "Horses on the lake shore"),
    "landscape-ne-ziway": ("Landscape NE of Ziway, September 2022.jpg", "Farmland north-east of Batu"),
    "zway-nasa": ("Zway NASA.jpg", "Lake Dambal seen from space"),
    "tulu-gudo-terraces": ("Terraces of Tulu Gudo Island, Lake Ziway 122017.jpg", "Terraced fields on Tulu Gudo island"),
    "tulu-gudo-landscape-1": ("Landscape on Tulu Gudo Island Lake Ziway December 2017 - 1.jpg", "Tulu Gudo island"),
    "tulu-gudo-landscape-2": ("Landscape on Tulu Gudo Island Lake Ziway December 2017 - 2.jpg", "Tulu Gudo island"),
    "cow-tulu-gudo": ("Cow on Tulu Gudo Island December 2017.jpg", "Farm life on Tulu Gudo"),
    "pelicans-on-lake-zway": ("Pelicans on Lake Zway.jpg", "Great white pelicans at Batu"),
    "marabou-storks": ("Marabou Storks in Lake Ziway.jpg", "Marabou storks at the jetty"),
    "marabou-stork": ("Marabou Stork in Lake Ziway.jpg", "A marabou stork at the jetty"),
    "hamerkop": ("Hamerkop at Lake Ziway.jpg", "Hamerkop at Lake Dambal"),
    "sacred-ibis": ("African Sacred Ibis in Lake Ziway.jpg", "African sacred ibis"),
    "egyptian-goose": ("Egyptian Goose (Alopochen aegyptiaca), Lake Ziway, Ethiopia.jpg", "Egyptian goose"),
    "pelican-flight": ("Great white pelican (Pelecanus onocrotalus) in flight Ethiopia.jpg", "Great white pelican in flight"),
    "marabou-flight": ("Marabou stork (Leptoptilos crumenifer) in flight.jpg", "Marabou stork in flight"),
}

# Reference photos supplied in the project folder (source and licence still to confirm).
LOCAL = {
    "corridor-aerial": ("../lake.jpg.jfif", "The new lakeside corridor and civic buildings"),
    "town-aerial": ("../town.jpg.jfif", "Batu and the main road from the air"),
    "pelicans-local": ("../pelicans.jpg.jfif", "Pelicans on the lake"),
}


def get(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            wait = 5 * (i + 1)
            print(f"  retry in {wait}s: {e}")
            time.sleep(wait)
    raise RuntimeError(f"failed: {url}")


def meta(filename):
    q = urllib.parse.urlencode({
        "action": "query", "titles": "File:" + filename, "prop": "imageinfo",
        "iiprop": "url|extmetadata", "iiurlwidth": 1600, "format": "json",
    })
    data = json.loads(get("https://commons.wikimedia.org/w/api.php?" + q))
    page = next(iter(data["query"]["pages"].values()))
    ii = page["imageinfo"][0]
    m = ii.get("extmetadata", {})
    artist = re.sub(r"<[^>]+>", "", m.get("Artist", {}).get("value", "")).strip()
    return {
        "thumb": ii.get("thumburl") or ii["url"],
        "page": ii["descriptionurl"],
        "artist": artist or "See Commons page",
        "licence": m.get("LicenseShortName", {}).get("value", ""),
        "licence_url": m.get("LicenseUrl", {}).get("value", ""),
    }


def main():
    IMG.mkdir(parents=True, exist_ok=True)
    media = {}
    out = ROOT / "data" / "media.json"
    if out.exists():
        media = json.loads(out.read_text(encoding="utf8"))
    for slug, (fn, caption) in COMMONS.items():
        big = IMG / f"{slug}-1600.jpg"
        small = IMG / f"{slug}-800.jpg"
        if big.exists() and small.exists() and slug in media:
            continue
        print("fetch", slug)
        info = meta(fn)
        time.sleep(1.5)
        big.write_bytes(get(info["thumb"]))
        time.sleep(1.5)
        small.write_bytes(get(info["thumb"].replace("/1600px-", "/800px-")))
        time.sleep(1.5)
        media[slug] = {"caption": caption, "credit": info["artist"], "licence": info["licence"],
                       "licence_url": info["licence_url"], "source": info["page"], "kind": "commons"}
        out.write_text(json.dumps(media, indent=1, ensure_ascii=False), encoding="utf8")
    for slug, (rel, caption) in LOCAL.items():
        src = (ROOT / rel).resolve()
        if src.exists():
            shutil.copyfile(src, IMG / f"{slug}-800.jpg")
            shutil.copyfile(src, IMG / f"{slug}-1600.jpg")
            media[slug] = {"caption": caption, "credit": "Reference photo from the project team",
                           "licence": "Source and licence to be confirmed", "licence_url": "",
                           "source": "", "kind": "reference"}
    out.write_text(json.dumps(media, indent=1, ensure_ascii=False), encoding="utf8")
    print("done", len(media))


if __name__ == "__main__":
    main()
