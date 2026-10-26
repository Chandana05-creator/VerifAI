"""VerifAI — backend/services/json_utils.py
Small helpers that make LLM output handling robust (code fences, extra prose, list content)."""
import json
import re


def llm_text(response) -> str:
    """Return the text of a LangChain chat response, whatever shape `content` has."""
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type", "text") == "text":
                parts.append(part.get("text", ""))
        return "".join(parts)
    return str(content)


def parse_json(raw: str):
    """Parse JSON from an LLM answer. Handles ```json fences and text around the JSON.
    Raises ValueError if nothing parseable is found."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("[", "]"), ("{", "}")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("No valid JSON found in model output")
