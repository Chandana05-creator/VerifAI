"""Lists the Gemini models your API key can call.   Run from the backend folder:  python list_models.py"""
import warnings
warnings.filterwarnings("ignore")
import google.generativeai as genai
from config import settings

genai.configure(api_key=settings.gemini_api_key)
print("Models available to your key (usable with generateContent):\n")
for m in genai.list_models():
    if "generateContent" in m.supported_generation_methods:
        print("  " + m.name.replace("models/", ""))
print("\nSet GEMINI_MODEL_STRONG and GEMINI_MODEL_FAST in your .env to names from this list.")
