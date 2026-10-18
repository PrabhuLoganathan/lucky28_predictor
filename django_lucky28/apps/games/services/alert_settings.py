"""Live configuration shared by web and worker processes, with a private token file."""
from dataclasses import dataclass, field
import os
from pathlib import Path
import tempfile

from django.conf import settings
from games.models import AlertSettings


@dataclass(frozen=True)
class Configuration:
    telegram_enabled: bool
    collection_timeout_minutes: int
    max_event_age_seconds: int
    bot_token: str = field(repr=False)


def get_config():
    saved = AlertSettings.objects.filter(pk=1).first()
    try:
        token = (Path(settings.ALERT_STATE_DIR) / 'bot-token').read_text().strip()
    except FileNotFoundError:
        token = settings.ALERT_TELEGRAM_BOT_TOKEN
    return Configuration(
        telegram_enabled=saved.telegram_enabled if saved else settings.ALERT_TELEGRAM_ENABLED,
        collection_timeout_minutes=saved.collection_timeout_minutes if saved else settings.ALERT_COLLECTION_TIMEOUT_MINUTES,
        max_event_age_seconds=saved.max_event_age_seconds if saved else settings.ALERT_MAX_EVENT_AGE_SECONDS,
        bot_token=token,
    )


def save_token(token):
    directory = Path(settings.ALERT_STATE_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.bot-token-', dir=directory)
    try:
        with os.fdopen(descriptor, 'w') as handle:
            handle.write(token.strip())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, directory / 'bot-token')
    finally:
        if os.path.exists(name):
            os.unlink(name)
