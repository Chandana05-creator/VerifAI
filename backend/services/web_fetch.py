"""VerifAI — backend/services/web_fetch.py
Safely downloads a web page and extracts its readable text (used for the "check a link" input).

Safety: only http(s); the host must resolve to a public address (blocks localhost / private networks);
redirects are followed manually and re-checked; the download is size- and time-limited."""
import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from config import settings

MAX_BYTES = 2_000_000
MAX_REDIRECTS = 4
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; VerifAI/1.0; +fact-checking research project)",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.5"}


async def validate_public_url(url: str) -> None:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("Only http:// and https:// links are supported.")
    if settings.allow_private_urls:
        return
    port = p.port or (443 if p.scheme == "https" else 80)
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, p.hostname, port, 0, socket.SOCK_STREAM)
    except socket.gaierror:
        raise ValueError(f"Could not find the website '{p.hostname}'.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            raise ValueError("That address points to a private or local network, which is not allowed.")


def extract_article(html: str) -> dict:
    """Return {'title', 'text'} — the main readable text of an HTML page."""
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        title = og["content"].strip()
    elif soup.title and soup.title.string:
        title = soup.title.string.strip()
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "form", "iframe", "svg"]):
        tag.decompose()

    def paragraphs(root) -> list[str]:
        out = [t.get_text(" ", strip=True) for t in root.find_all(["p", "h1", "h2", "h3", "li", "blockquote"])]
        return [t for t in out if len(t.split()) >= 5]       # drops menu items and captions

    root = soup.find("article") or soup.find("main") or soup.body or soup
    paras = paragraphs(root)
    if len(" ".join(paras)) < 200 and root is not soup.body and soup.body:
        paras = paragraphs(soup.body)
    text = "\n".join(paras)
    return {"title": title[:200], "text": text[:settings.max_article_chars]}


async def fetch_article(url: str) -> dict:
    """Download `url` and return {'title', 'text', 'url'}. Raises ValueError with a readable message."""
    current = url.strip()
    async with httpx.AsyncClient(timeout=15, follow_redirects=False, headers=_HEADERS) as client:
        for _ in range(MAX_REDIRECTS + 1):
            await validate_public_url(current)
            try:
                async with client.stream("GET", current) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                        current = urljoin(current, resp.headers["location"])
                        continue
                    if resp.status_code >= 400:
                        raise ValueError(f"The website answered with an error ({resp.status_code}).")
                    ctype = resp.headers.get("content-type", "")
                    if ctype and not any(t in ctype for t in ("text/html", "text/plain", "application/xhtml")):
                        raise ValueError(f"This link is not a web page ({ctype.split(';')[0]}).")
                    data = b""
                    async for chunk in resp.aiter_bytes():
                        data += chunk
                        if len(data) > MAX_BYTES:
                            break
                    html = data.decode(resp.encoding or "utf-8", errors="replace")
            except httpx.HTTPError as e:
                raise ValueError(f"Could not download the page: {str(e)[:120]}")
            if "text/plain" in ctype:
                return {"title": "", "text": html[:settings.max_article_chars], "url": current}
            art = extract_article(html)
            return {**art, "url": current}
    raise ValueError("Too many redirects.")
