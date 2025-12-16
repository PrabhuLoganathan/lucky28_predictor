import os
import django
from django.template.loader import render_to_string
from django.conf import settings

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lucky28_backend.settings")
django.setup()

def debug():
    try:
        render_to_string("games/dashboard.html", {})
        print("Template rendered successfully (unexpectedly).")
    except Exception as e:
        print(f"Error rendering template: {e}")

if __name__ == "__main__":
    debug()
