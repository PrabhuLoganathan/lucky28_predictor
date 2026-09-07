"""Export saved game history (newest first) to the CSV import format."""

import csv
import re
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path


INPUT_FILE = Path(__file__).resolve().with_name('14th.html')
OUTPUT_FILE = Path(__file__).resolve().with_name('14th.csv')

# Supplies the year for MM.DD labels, or the newest date if no labels exist.
DATE_PREFIX = '2026-09-06'
FIELDNAMES = ['result', 'timestamp', 'winners_count', 'prize_amount']
HTML_FIELDS = ('time', 'result', 'winners', 'prizes')


class HistoryParser(HTMLParser):
    """Collect each history row's text without including headers or attributes."""

    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.depth = 0
        self.field = None
        self.field_depth = None

    def handle_starttag(self, tag, attrs):
        if tag != 'div':
            return
        classes = (dict(attrs).get('class') or '').split()
        if self.row is None:
            if 'van-cell-group' in classes:
                self.row = {}
                self.depth = 1
            return

        self.depth += 1
        if self.field is None:
            for field in HTML_FIELDS:
                if field in classes:
                    self.field = field
                    self.field_depth = self.depth
                    self.row.setdefault(field, [])
                    break

    def handle_data(self, data):
        if self.field is not None:
            self.row[self.field].append(data)

    def handle_endtag(self, tag):
        if tag != 'div' or self.row is None:
            return
        if self.depth == self.field_depth:
            self.field = None
            self.field_depth = None
        self.depth -= 1
        if self.depth == 0:
            self.rows.append({key: ''.join(value).strip()
                              for key, value in self.row.items()})
            self.row = None


def parse_amount(value):
    """Convert displayed integers and K/M/B amounts without float rounding."""
    match = re.fullmatch(r'(\d[\d,]*(?:\.\d+)?)\s*([KMB]?)', value, re.I)
    if not match:
        raise ValueError(f'Invalid amount: {value!r}')
    multiplier = {'': 1, 'K': 1000, 'M': 1000000, 'B': 1000000000}
    amount = Decimal(match[1].replace(',', '')) * multiplier[match[2].upper()]
    if amount != amount.to_integral_value():
        raise ValueError(f'Amount is not a whole number: {value!r}')
    return str(int(amount))


def parse_timestamp(value, reference_date):
    if '.' in value:
        return datetime.strptime(f'{reference_date.year}.{value}', '%Y.%m.%d %H:%M')
    time = datetime.strptime(value, '%H:%M').time()
    return datetime.combine(reference_date, time)


def resolve_timestamps(rows, date_prefix):
    """Use date labels and midnight crossings in newest-first history."""
    reference_date = datetime.strptime(date_prefix, '%Y-%m-%d').date()
    anchor = next((i for i, row in enumerate(rows) if '.' in row['time']), 0)
    timestamps = [None] * len(rows)
    timestamps[anchor] = parse_timestamp(rows[anchor]['time'], reference_date)

    # Undated rows above the first dated row are newer, possibly after midnight.
    for i in range(anchor - 1, -1, -1):
        timestamp = parse_timestamp(rows[i]['time'], timestamps[i + 1].date())
        if timestamp < timestamps[i + 1]:
            timestamp += timedelta(days=1)
        timestamps[i] = timestamp

    for i in range(anchor + 1, len(rows)):
        previous = timestamps[i - 1]
        timestamp = parse_timestamp(rows[i]['time'], previous.date())
        if timestamp > previous:
            if '.' in rows[i]['time']:
                reference_date = previous.date().replace(year=previous.year - 1, day=1)
                timestamp = parse_timestamp(rows[i]['time'], reference_date)
            else:
                timestamp -= timedelta(days=1)
        timestamps[i] = timestamp
    return timestamps


def extract_data(input_file=None, output_file=None, date_prefix=None):
    input_file = Path(INPUT_FILE if input_file is None else input_file)
    output_file = Path(OUTPUT_FILE if output_file is None else output_file)
    date_prefix = DATE_PREFIX if date_prefix is None else date_prefix

    parser = HistoryParser()
    parser.feed(input_file.read_text(encoding='utf-8'))
    parser.close()
    if parser.row is not None:
        raise ValueError('The HTML ends with an incomplete history row')
    if not parser.rows:
        raise ValueError('No history rows found in the HTML')

    data = []
    for i, row in enumerate(parser.rows, start=1):
        try:
            missing = [field for field in HTML_FIELDS if not row.get(field)]
            if missing:
                raise ValueError(f'Missing fields: {", ".join(missing)}')
            result = re.fullmatch(r'(\d+)(?:\s*\([^)]*\))?', row['result'])
            if not result:
                raise ValueError(f'Invalid result: {row["result"]!r}')
            data.append({
                'result': result[1],
                'winners_count': parse_amount(row['winners']),
                'prize_amount': parse_amount(row['prizes']),
            })
        except ValueError as error:
            raise ValueError(f'History row {i}: {error}') from error

    for row, timestamp in zip(data, resolve_timestamps(parser.rows, date_prefix)):
        row['timestamp'] = timestamp.strftime('%Y-%m-%d %H:%M:%S')

    # Validate the entire input before replacing an existing export.
    with output_file.open('w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=FIELDNAMES, lineterminator='\n')
        writer.writeheader()
        writer.writerows(data)

    print(f'Successfully wrote {len(data)} rows to {output_file}')
    return data


if __name__ == '__main__':
    try:
        extract_data()
    except (OSError, ValueError) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
