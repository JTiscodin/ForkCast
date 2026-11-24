# Tests never touch live services: without this, importing app.py loads backend/.env and,
# with a valid Swiggy login, starts the live catalogue warm-up, reminders and Gemini calls.
# Set before any test module imports config (which only fills keys that are missing).
import os

os.environ["SWIGGY_MODE"] = "mock"
os.environ["DAILY_SCHEDULER"] = "0"
os.environ["GEMINI_API_KEY"] = ""
