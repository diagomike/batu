"""Tell Afaan Oromoo, Amharic and English apart in short answers.

Amharic is easy (Ethiopic script). Afaan Oromoo and English both use Latin
letters, so we count common function words and Oromo spelling patterns
(double vowels, dh/ny/ch, the glottal apostrophe).
"""
from __future__ import annotations

import re

WORD = re.compile(r"[a-z']+")
OM = set("""fi kan akka irratti keessatti ykn yoo isin keessan kee koo ni hin waan kana sana kun sun qaba qabu jira jiru
ta'e ta'uu irraa gara hanga bakka yeroo guyyaa waajjira tajaajila tajaajiloota magaalaa bilbilaa bilbili argachuu
danda'a danda'u qofa malee waliin booda dura amma itti isaa ishee keenya keessa ganda gandoota bulchiinsa
kaffaltii barbaachisa barbaadi gaafadhaa deemaa dhiyeessaa iyyachuu jedhu jedha hundaa garuu akkasumas""".split())
EN = set("""the and is are to of for you your in on with can call at from this it be by an or not if
what when where how which who will need have has was were please there their than then also only""".split())


def detect(text: str) -> str:
    letters = sum(ch.isalpha() for ch in text) or 1
    ethiopic = sum("ሀ" <= ch <= "፿" for ch in text)
    if ethiopic / letters > 0.3:
        return "am"
    words = WORD.findall(text.lower())
    if not words:
        return "en"
    om = sum(w in OM for w in words)
    om += 0.5 * sum(bool(re.search(r"(aa|ee|ii|oo|uu|dh|ny|[aeiou]'[aeiou])", w)) for w in words if len(w) > 3)
    en = sum(w in EN for w in words) * 1.2
    return "om" if om > en else "en"


def matches(text: str, lang: str) -> bool:
    return detect(text) == lang
