"""Stable, shared visual identities for group cards and their text captions."""
from games.category_config import CATEGORY_BY_ID
from games.group_config import GROUP_BY_ID


def group_identity(payload):
    group_id = payload.get('group_id')
    category = CATEGORY_BY_ID.get(group_id)
    if category:
        if category.family == 'Rows':
            return dict(family='ROW', accent='#54d9ed', icon='row', badge=f'R{int(group_id[1:])}',
                        symbol='↔️', title=category.name)
        if category.family == 'Columns':
            return dict(family='COLUMN', accent='#ffbd69', icon='column', badge=f'C{int(group_id[1:])}',
                        symbol='↕️', title=category.name)
        return dict(family='COMBINATION', accent='#c29aff', icon='combination', badge=group_id,
                    symbol='🔷', title=category.name)
    color = GROUP_BY_ID.get(group_id)
    if color:
        return dict(family='COLOR', accent=color.color, icon='color_group', badge=group_id,
                    symbol='🎨', title=f'{group_id} · {color.name}')
    return None


def group_heading(payload, mode='absence', ended=False):
    identity = group_identity(payload)
    family = identity['family'] if identity else 'GROUP'
    return f'{family} {mode.upper()} {"ENDED" if ended else "ALERT"}'
