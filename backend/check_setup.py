"""VerifAI setup checker.   Run from the backend folder:  python check_setup.py
Tests each dependency on its own and tells you exactly what to fix."""
import asyncio
import sys

FAILED = []


def ok(msg):
    print(f"  [ OK ]  {msg}")


def bad(msg, hint=""):
    FAILED.append(msg)
    print(f"  [FAIL]  {msg}")
    if hint:
        print(f"          -> {hint}")


def hint_for(err: str) -> str:
    e = err.lower()
    if "404" in e or "not found" in e:
        return "That model name is not available to your key. Run `python list_models.py` and update GEMINI_MODEL_STRONG / GEMINI_MODEL_FAST in .env"
    if "429" in e or "quota" in e or "resource" in e and "exhaust" in e:
        return "Rate limit / quota reached. Wait a minute and retry, or enable billing on the key."
    if "api key" in e or "api_key" in e or "403" in e or "permission" in e or "401" in e or "invalid" in e:
        return "The API key looks invalid. Re-copy it into .env (no quotes, no spaces)."
    if "connect" in e or "timeout" in e or "resolve" in e:
        return "Network problem. Check your internet connection / VPN / firewall."
    return "See the message above."


async def main():
    print("\nVerifAI setup check\n")

    v = sys.version_info
    if (v.major, v.minor) in ((3, 11), (3, 12)):
        ok(f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        bad(f"Python {v.major}.{v.minor}.{v.micro} is not a tested version",
            "Use Python 3.11 (or 3.12). Newer versions often cannot install the required packages.")

    for module, package in (("bs4", "beautifulsoup4"), ("fpdf", "fpdf2"), ("multipart", "python-multipart")):
        try:
            __import__(module)
            ok(f"Package {package} installed")
        except ImportError:
            bad(f"Package {package} is missing", "Run  pip install -r requirements.txt  (or setup.bat again)")

    from config import settings
    if settings.gemini_api_key:
        ok("GEMINI_API_KEY is set")
    else:
        bad("GEMINI_API_KEY is empty", "Add it to the .env file in the verifai folder")
    if settings.tavily_api_key:
        ok("TAVILY_API_KEY is set")
    else:
        bad("TAVILY_API_KEY is empty", "Add it to the .env file in the verifai folder")

    try:
        from services.session_store import init_db, engine
        await init_db()
        ok(f"Database reachable ({engine.url.get_backend_name()})")
    except Exception as e:
        bad(f"Database error: {str(e)[:150]}",
            "Leave DATABASE_URL out of .env to use the built-in SQLite file, or start PostgreSQL if you set one.")

    if settings.gemini_api_key:
        from services.llm_factory import get_llm
        for tier, model in (("strong", settings.gemini_model_strong), ("fast", settings.gemini_model_fast)):
            try:
                resp = await get_llm(tier).ainvoke("Reply with the single word OK")
                from services.json_utils import llm_text
                ok(f"Gemini model '{model}' ({tier}) answered: {llm_text(resp).strip()[:20]!r}")
            except Exception as e:
                bad(f"Gemini model '{model}' ({tier}) failed: {str(e)[:150]}", hint_for(str(e)))

    if settings.tavily_api_key:
        from services.tavily_client import get_tavily, as_results
        try:
            raw = await get_tavily(1, "basic").ainvoke("height of the Eiffel Tower")
            if as_results(raw):
                ok("Tavily search returned results")
            else:
                bad(f"Tavily returned no results: {str(raw)[:150]}", "Check TAVILY_API_KEY and your internet connection")
        except Exception as e:
            bad(f"Tavily failed: {str(e)[:150]}", hint_for(str(e)))

    print()
    if FAILED:
        print(f"{len(FAILED)} problem(s) found. Fix them and run this check again.\n")
        sys.exit(1)
    print("All checks passed. Start the app, then open http://localhost:8000/\n")


asyncio.run(main())
