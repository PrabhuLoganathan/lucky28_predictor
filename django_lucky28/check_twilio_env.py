import os
import django
from django.conf import settings

def check_env():
    print("--- Twilio Credential Check ---")
    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    number = os.environ.get("TWILIO_WHATSAPP_NUMBER")
    
    print(f"ACCOUNT_SID: {sid[:5]}...{sid[-5:] if sid else 'None'}")
    print(f"AUTH_TOKEN:  {'*' * 5}...{'*' * 5 if token else 'None'}")
    # Show length to hint if copy-paste error included space
    print(f"SID Length: {len(sid) if sid else 0}")
    print(f"Token Length: {len(token) if token else 0}")
    print(f"FROM_NUMBER: {number}")
    print("-------------------------------")

if __name__ == "__main__":
    from pathlib import Path
    from dotenv import load_dotenv
    # Load .env same way manage.py does
    env_path = Path(__file__).resolve().parent.parent / '.env'
    load_dotenv(dotenv_path=env_path)
    
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lucky28_backend.settings")
    django.setup()
    check_env()
