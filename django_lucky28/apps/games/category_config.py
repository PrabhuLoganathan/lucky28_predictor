"""Board rows, vertical columns and size/parity categories from the game layout."""
from dataclasses import dataclass


@dataclass(frozen=True)
class NumberCategory:
    id: str
    name: str
    family: str
    numbers: tuple

    @property
    def label(self):
        return f'{self.name} [{", ".join(map(str, self.numbers))}]'


ROW_GROUPS = tuple(NumberCategory(f'R{i + 1:02}', f'Row {i + 1}', 'Rows', tuple(range(i * 7, i * 7 + 7))) for i in range(4))
COLUMN_GROUPS = tuple(NumberCategory(f'C{i + 1:02}', f'Column {i + 1}', 'Columns', tuple(range(i, 28, 7))) for i in range(7))
COMBO_GROUPS = (
    NumberCategory('SE', 'SE — Small Even', 'SE / BE / BO / SO', tuple(range(0, 14, 2))),
    NumberCategory('BE', 'BE — Big Even', 'SE / BE / BO / SO', tuple(range(14, 28, 2))),
    NumberCategory('BO', 'BO — Big Odd', 'SE / BE / BO / SO', tuple(range(15, 28, 2))),
    NumberCategory('SO', 'SO — Small Odd', 'SE / BE / BO / SO', tuple(range(1, 14, 2))),
)
CATEGORY_FAMILIES = (('Rows', ROW_GROUPS), ('Columns', COLUMN_GROUPS), ('SE / BE / BO / SO', COMBO_GROUPS))
CATEGORIES = ROW_GROUPS + COLUMN_GROUPS + COMBO_GROUPS
CATEGORY_BY_ID = {group.id: group for group in CATEGORIES}
CATEGORIES_BY_NUMBER = {number: tuple(group for group in CATEGORIES if number in group.numbers) for number in range(28)}
CATEGORY_MODES = ('absence', 'streak')
