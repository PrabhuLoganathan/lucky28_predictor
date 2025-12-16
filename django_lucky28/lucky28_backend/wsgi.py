import os
from pathlib import Path
from dotenv import load_dotenv
from django.core.wsgi import get_wsgi_application

# Load .env from project root (two levels up from wsgi.py, then one more for repo root?)
# Structure: repo/django_lucky28/lucky28_backend/wsgi.py
# repo is 3 levels up from wsgi.py
env_path = Path(__file__).resolve().parent.parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

os.environ.setdefault('DJANGO_SETTINGS_MODULE','lucky28_backend.settings')
application = get_wsgi_application()
