"""Content-versioned assets for pages served without a static manifest."""
from hashlib import sha256
from pathlib import Path

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def timeline_asset(name):
    url = static(name)
    source = finders.find(name)
    if source:
        version = sha256(Path(source).read_bytes()).hexdigest()[:16]
        return f'{url}{"&" if "?" in url else "?"}v={version}'
    # A deployed manifest storage may already supply a hashed asset URL.
    return url
