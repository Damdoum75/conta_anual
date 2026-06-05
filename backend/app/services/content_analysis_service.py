from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Optional
import re

import httpx


@dataclass
class ExtractedContent:
    url: str
    ok: bool
    status_code: Optional[int]
    error: Optional[str]
    title: str
    description: str
    og_title: str
    og_description: str
    text: str


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_script = False
        self._in_style = False
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        t = tag.lower()
        if t == "script":
            self._in_script = True
        elif t == "style":
            self._in_style = True

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "script":
            self._in_script = False
        elif t == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_script or self._in_style:
            return
        s = (data or "").strip()
        if s:
            self._chunks.append(s)

    def get_text(self) -> str:
        joined = " ".join(self._chunks)
        joined = re.sub(r"\s+", " ", joined).strip()
        return joined


def _first_regex_group(pattern: str, text: str) -> str:
    m = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    return re.sub(r"\s+", " ", (m.group(1) or "").strip())


def _extract_meta_content(html: str, *, name: str | None = None, prop: str | None = None) -> str:
    if name:
        pattern = r'<meta[^>]+name=["\']' + re.escape(name) + r'["\'][^>]*content=["\']([^"\']+)["\']'
        v = _first_regex_group(pattern, html)
        if v:
            return v
        pattern = r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*name=["\']' + re.escape(name) + r'["\']'
        return _first_regex_group(pattern, html)
    if prop:
        pattern = r'<meta[^>]+property=["\']' + re.escape(prop) + r'["\'][^>]*content=["\']([^"\']+)["\']'
        v = _first_regex_group(pattern, html)
        if v:
            return v
        pattern = r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*property=["\']' + re.escape(prop) + r'["\']'
        return _first_regex_group(pattern, html)
    return ""


def extract_from_html(url: str, html: str) -> ExtractedContent:
    title = _first_regex_group(r"<title[^>]*>(.*?)</title>", html)
    description = _extract_meta_content(html, name="description")
    og_title = _extract_meta_content(html, prop="og:title")
    og_description = _extract_meta_content(html, prop="og:description")

    parser = _TextExtractor()
    parser.feed(html)
    text = parser.get_text()

    return ExtractedContent(
        url=url,
        ok=True,
        status_code=200,
        error=None,
        title=title,
        description=description,
        og_title=og_title,
        og_description=og_description,
        text=text,
    )


async def fetch_and_extract(url: str, *, timeout_s: float = 12.0) -> ExtractedContent:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TecTeamLabBot/1.0; +https://tecteamlab.eu/)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout_s, headers=headers) as client:
            resp = await client.get(url)
            content_type = (resp.headers.get("content-type") or "").lower()
            if "text/html" not in content_type and "application/xhtml+xml" not in content_type and "xml" not in content_type:
                return ExtractedContent(
                    url=url,
                    ok=False,
                    status_code=resp.status_code,
                    error=f"Unsupported content-type: {resp.headers.get('content-type')}",
                    title="",
                    description="",
                    og_title="",
                    og_description="",
                    text="",
                )

            html = resp.text or ""
            extracted = extract_from_html(url, html)
            extracted.status_code = resp.status_code
            extracted.ok = resp.status_code >= 200 and resp.status_code < 300
            if not extracted.ok:
                extracted.error = f"HTTP {resp.status_code}"
            return extracted
    except Exception as e:
        return ExtractedContent(
            url=url,
            ok=False,
            status_code=None,
            error=str(e),
            title="",
            description="",
            og_title="",
            og_description="",
            text="",
        )


def _detect_language(text: str) -> str:
    t = text or ""
    if re.search(r"[\u0600-\u06FF]", t):
        return "ar"
    if re.search(r"[ñáéíóúü]", t.lower()):
        return "es"
    if re.search(r"[àâçéèêëîïôùûüÿœæ]", t.lower()):
        return "fr"
    return "en"


def _keywords(text: str, *, lang: str, limit: int = 12) -> list[str]:
    stop_en = {"the", "and", "for", "with", "your", "from", "this", "that", "are", "you", "our", "into", "about", "more", "than"}
    stop_fr = {"les", "des", "une", "pour", "avec", "votre", "dans", "sur", "plus", "cela", "vous", "nous", "est", "être", "que", "qui"}
    stop_es = {"para", "con", "una", "que", "los", "las", "del", "por", "más", "esto", "esta", "como", "sus", "nuestro", "sobre"}
    stop_ar = {"في", "من", "على", "إلى", "عن", "هذا", "هذه", "ذلك", "كما", "مع", "هو", "هي", "و", "او"}
    stop = stop_en
    if lang == "fr":
        stop = stop_fr
    elif lang == "es":
        stop = stop_es
    elif lang == "ar":
        stop = stop_ar

    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ\u0600-\u06FF0-9]{3,}", (text or "").lower())
    freq: dict[str, int] = {}
    for w in words:
        if w in stop:
            continue
        freq[w] = freq.get(w, 0) + 1
    ranked = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    return [k for k, _ in ranked]


def analyze_text(text: str) -> dict:
    lang = _detect_language(text)
    hashtags = sorted(set(re.findall(r"#([A-Za-z0-9_\u0600-\u06FF]{2,})", text or "")))[:20]
    return {
        "language": lang,
        "keywords": _keywords(text, lang=lang),
        "hashtags": hashtags,
        "char_count": len(text or ""),
    }
