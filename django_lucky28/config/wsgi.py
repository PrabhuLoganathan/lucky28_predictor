import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from django.core.wsgi import get_wsgi_application

# Load .env from project root (two levels up from wsgi.py => django_lucky28, then one more for repo root)
env_path = Path(__file__).resolve().parent.parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Add apps to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent / 'apps'))

os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
application = get_wsgi_application()
