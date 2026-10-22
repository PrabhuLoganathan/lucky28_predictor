"""Stable identities and membership; display colors are not calculation keys."""
from dataclasses import dataclass
import re

MAX_GROUP_THRESHOLD = 1_000_000
THRESHOLD_ERROR = 'Enter a whole number of rounds greater than 0.'


@dataclass(frozen=True)
class ColorGroup:
    id: str
    name: str
    numbers: tuple
    color: str


COLOR_GROUPS = (
    ColorGroup('G01', 'Red', (0, 1, 26, 27), '#ef5350'),
    ColorGroup('G02', 'Orange', (2, 3, 24, 25), '#ff9800'),
    ColorGroup('G03', 'Magenta', (4, 5, 22, 23), '#e754cf'),
    ColorGroup('G04', 'Blue', (6, 7, 20, 21), '#669dff'),
    ColorGroup('G05', 'Cyan / Teal', (8, 9, 18, 19), '#31c8c4'),
    ColorGroup('G06', 'Green', (10, 11, 16, 17), '#6cca7b'),
    ColorGroup('G07', 'Grey', (12, 13, 14, 15), '#aab0bb'),
)
GROUP_BY_ID = {group.id: group for group in COLOR_GROUPS}
GROUP_BY_NUMBER = {number: group for group in COLOR_GROUPS for number in group.numbers}
GROUP_BY_NAME = {group.name: group for group in COLOR_GROUPS}
GROUP_BY_NAME.update({
    'Yellow': GROUP_BY_ID['G02'], 'Pink': GROUP_BY_ID['G03'],
    'Cyan': GROUP_BY_ID['G05'], 'Teal': GROUP_BY_ID['G05'], 'Gray': GROUP_BY_ID['G07'],
})
_COLOR_LABEL = re.compile(
    r'\b(' + '|'.join(re.escape(name) for name in sorted(GROUP_BY_NAME, key=len, reverse=True))
    + r')\b(?P<numbers>\s*\[[0-9,\s]+\])?'
)


def label_color_groups(text):
    """Add member numbers, including legacy color names, without double labels."""
    def label(match):
        if match.group('numbers'):
            return match.group()
        name = match.group(1)
        numbers = ', '.join(map(str, GROUP_BY_NAME[name].numbers))
        return f'{name} [{numbers}]'
    return _COLOR_LABEL.sub(label, text)


def parse_threshold(value, enabled=False):
    import re
    from django.core.exceptions import ValidationError
    value = '' if value is None else str(value).strip()
    if not value and not enabled:
        return None
    if not re.fullmatch(r'[0-9]{1,7}', value) or not 1 <= int(value) <= MAX_GROUP_THRESHOLD:
        raise ValidationError(f'{THRESHOLD_ERROR} Maximum: {MAX_GROUP_THRESHOLD:,}.')
    return int(value)
