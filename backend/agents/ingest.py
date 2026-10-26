"""VerifAI — backend/agents/ingest.py — turns a link, pasted text or an image into text to fact-check."""
import base64
from langchain_core.messages import HumanMessage
from services.llm_factory import get_llm
from services.json_utils import llm_text
from services import inputs
from services.web_fetch import fetch_article
from config import settings

_IMAGE_PROMPT = ("Transcribe all readable text in this image exactly as written (a screenshot of a message, "
                 "social-media post, news headline, poster or document). Keep the original language. "
                 "Output only the transcribed text. If the image contains no readable text, output NO_TEXT.")


async def _read_image(session_id: str) -> dict:
    payload = inputs.pop(session_id)
    if not payload:
        raise ValueError("The uploaded image is no longer available — please upload it again.")
    b64 = base64.b64encode(payload["data"]).decode()
    msg = HumanMessage(content=[{"type": "text", "text": _IMAGE_PROMPT},
                                {"type": "image_url", "image_url": {"url": f"data:{payload['mime']};base64,{b64}"}}])
    text = llm_text(await get_llm("strong").ainvoke([msg])).strip()
    if not text or text.upper().startswith("NO_TEXT"):
        raise ValueError("No readable text was found in the image.")
    return {"text": text[:settings.max_article_chars], "title": payload.get("filename") or "Uploaded image", "url": ""}


async def run_ingest(kind: str, value: str, session_id: str) -> dict:
    """Returns {'text', 'title', 'url'}."""
    if kind == "url":
        art = await fetch_article(value)
        return {"text": art["text"], "title": art["title"], "url": art["url"]}
    if kind == "text":
        return {"text": value.strip()[:settings.max_article_chars], "title": "Pasted text", "url": ""}
    if kind == "image":
        return await _read_image(session_id)
    raise ValueError(f"Unknown input type: {kind}")
