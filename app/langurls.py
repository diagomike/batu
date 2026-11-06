"""Language in the address: /om/services shows Afaan Oromoo, /am/services Amharic, /en/services English.

The same addresses as the static build (tools/build_static.py), so links and bookmarks work on both.
Unprefixed addresses keep working as before (language from the cookie, default English).
The middleware strips the prefix, tells the app the language, and puts the prefix back on the
links in the HTML it returns (and on redirects), so visitors stay in their language.
"""
from __future__ import annotations

import re

LANGS = ("om", "am", "en")
_PREFIX = re.compile(r"^/(om|am|en)(/.*)?$")
_SKIP = ("/static/", "/api/", "/admin", "/health")
_ATTR = re.compile(rb'((?:href|action)=")(/(?!/)[^"]*)"')
_PAL = re.compile(rb'("u":\s*")(/(?!/)[^"]*)"')
_SWITCH = re.compile(r"^/settings/lang/(om|am|en)(?:\?back=([^&#]*))?")


def _local(prefix: str, url: str) -> str:
    """Prefix an app-relative URL, leaving static files, the API and the studio alone."""
    m = _SWITCH.match(url)
    if m:  # language switcher: go straight to the same page in the other language
        from urllib.parse import unquote
        back = unquote(m.group(2) or "/")
        return f"/{m.group(1)}{back if back.startswith('/') else '/'}"
    if url.startswith("/settings/lowdata"):  # keep the language when coming back
        return re.sub(r"back=/(?!(?:om|am|en)/)", f"back={prefix}/", url)
    if url.startswith(_SKIP) or _PREFIX.match(url.split("?")[0].split("#")[0]):
        return url
    return prefix + url


class LangPrefix:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        m = _PREFIX.match(scope["path"])
        if not m:
            return await self.app(scope, receive, send)
        lang, rest = m.group(1), m.group(2) or "/"
        prefix = "/" + lang
        cookies = [c.strip() for h, v in scope["headers"] if h == b"cookie" for c in v.decode("latin-1").split(";")]
        cookies = [c for c in cookies if c and not c.startswith("lang=")] + [f"lang={lang}"]
        headers = [(h, v) for h, v in scope["headers"] if h != b"cookie"] + [(b"cookie", "; ".join(cookies).encode("latin-1"))]
        scope = dict(scope, path=rest, raw_path=rest.encode(), headers=headers)

        start = {}
        body = []

        async def send_wrapped(message):
            if message["type"] == "http.response.start":
                hdrs = []
                for h, v in message.get("headers", []):
                    if h.lower() == b"location":
                        v = _local(prefix, v.decode("latin-1")).encode("latin-1")
                    hdrs.append((h, v))
                message = dict(message, headers=hdrs)
                ctype = next((v for h, v in hdrs if h.lower() == b"content-type"), b"")
                if ctype.startswith(b"text/html"):
                    start.update(message)  # hold until the body is rewritten
                    return
                return await send(message)
            if message["type"] == "http.response.body" and start:
                body.append(message.get("body", b""))
                if message.get("more_body"):
                    return
                html = b"".join(body)
                fix = lambda mm: mm.group(1) + _local(prefix, mm.group(2).decode("utf8")).encode("utf8") + b'"'  # noqa: E731
                html = _PAL.sub(fix, _ATTR.sub(fix, html))
                hdrs = [(h, v) for h, v in start["headers"] if h.lower() != b"content-length"]
                hdrs.append((b"content-length", str(len(html)).encode()))
                await send(dict(start, headers=hdrs))
                return await send({"type": "http.response.body", "body": html})
            return await send(message)

        return await self.app(scope, receive, send_wrapped)
