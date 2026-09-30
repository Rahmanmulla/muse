"""STIP backend — v3 link previews.

Fetches a URL's title/description/image server-side so clients don't have
to. SSRF-hardened: only http/https, hostname must resolve to a public IP
(private/loopback/link-local/multicast/reserved/unspecified ranges are
refused — re-checked on every redirect), 3 redirects max, 5s timeouts,
1MB body cap, HTML only, 24h in-memory cache.

Known limitation: DNS is resolved at check time and again at connect
time, so a hostile DNS that flips between the two could bypass the IP
check (DNS-rebinding TOCTOU). A production hardening would pin the
validated IP for the connection. Not a concern for the dev threat model.

No third-party HTTP client is used (stdlib urllib only).
"""
from __future__ import annotations

import ipaddress
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models as m
from auth import get_current_user, rate_limit
from db import get_db

router = APIRouter()

MAX_REDIRECTS = 3
FETCH_TIMEOUT = 5
BODY_CAP = 1024 * 1024
CACHE_TTL = 24 * 3600
CACHE_MAX = 1000

_cache: dict[str, tuple[float, dict]] = {}


class _MetaParser(HTMLParser):
    """Collect og:title / og:description / og:image and the <title>."""

    def __init__(self):
        super().__init__()
        self.og: dict[str, str] = {}
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            prop = (a.get("property") or a.get("name") or "").lower()
            if prop in ("og:title", "og:description", "og:image") and a.get("content"):
                self.og.setdefault(prop, a["content"][:500])
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def _guard_url(url: str) -> urllib.parse.ParseResult:
    """SSRF guard: scheme + resolvable hostname -> public IP only."""
    if len(url) > 2048:
        raise HTTPException(400, "URL too long.")
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        raise HTTPException(400, "Invalid URL.")
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(400, "Only http(s) URLs can be previewed.")
    host = parsed.hostname
    if not host or parsed.username or parsed.password:
        raise HTTPException(400, "Invalid URL.")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80),
                                   type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise HTTPException(400, "Could not resolve host.")
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            raise HTTPException(400, "Could not resolve host.")
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                or ip.is_reserved or ip.is_unspecified):
            raise HTTPException(400, "Preview of that address is blocked.")
    return parsed


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # we follow redirects manually so each hop is SSRF-checked


_opener = urllib.request.build_opener(_NoRedirect)


def _fetch(url: str) -> dict:
    hops = 0
    while True:
        parsed = _guard_url(url)
        req = urllib.request.Request(
            url, headers={"User-Agent": "STIP-LinkPreview/1.0 (+https://stip.app)"})
        try:
            resp = _opener.open(req, timeout=FETCH_TIMEOUT)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and hops < MAX_REDIRECTS:
                loc = e.headers.get("Location")
                if not loc:
                    raise HTTPException(400, "Redirect without Location.")
                url = urllib.parse.urljoin(url, loc)
                hops += 1
                continue
            raise HTTPException(400, f"Could not fetch URL (HTTP {e.code}).")
        except (urllib.error.URLError, socket.timeout, OSError, ValueError):
            raise HTTPException(400, "Could not fetch URL.")
        with resp:
            status = resp.status
            if status in (301, 302, 303, 307, 308):
                if hops >= MAX_REDIRECTS:
                    raise HTTPException(400, "Too many redirects.")
                loc = resp.headers.get("Location")
                if not loc:
                    raise HTTPException(400, "Redirect without Location.")
                url = urllib.parse.urljoin(url, loc)
                hops += 1
                continue
            if status != 200:
                raise HTTPException(400, f"Could not fetch URL (HTTP {status}).")
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "html" not in ctype:
                return {"url": url, "title": None, "description": None, "image": None}
            raw = resp.read(BODY_CAP + 1)
            if len(raw) > BODY_CAP:
                raise HTTPException(400, "Page too large to preview.")
            text = raw.decode("utf-8", errors="replace")
            parser = _MetaParser()
            try:
                parser.feed(text[:500_000])  # parse head only
            except Exception:
                pass
            title = parser.og.get("og:title") or parser.title.strip()[:300] or None
            image = parser.og.get("og:image")
            if image:
                image = urllib.parse.urljoin(url, image)
            return {"url": url, "title": title,
                    "description": parser.og.get("og:description"), "image": image}


def _cached(url: str) -> dict:
    now = time.time()
    hit = _cache.get(url)
    if hit and hit[0] > now:
        return hit[1]
    result = _fetch(url)
    if len(_cache) >= CACHE_MAX:
        _cache.pop(next(iter(_cache)))
    _cache[url] = (now + CACHE_TTL, result)
    return result


@router.get("/preview")
def link_preview(url: str, user: m.User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """SSRF-guarded link preview: {url, title, description, image}."""
    rate_limit(f"preview:{user.id}", 30, 60)
    return _cached(url)
