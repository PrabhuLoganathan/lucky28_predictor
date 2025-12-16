import os
import sys
from pathlib import Path
from django.core.asgi import get_asgi_application

# Add apps to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent / 'apps'))

os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
application = get_asgi_application()
