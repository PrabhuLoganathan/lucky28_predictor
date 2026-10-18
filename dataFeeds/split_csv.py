import csv
from collections import defaultdict
import os

input_file = '/Users/nilav/Documents/GitHub/lucky28_predictor/dataFeeds/14th.csv'
output_dir = '/Users/nilav/Documents/GitHub/lucky28_predictor/dataFeeds/split_by_date'

os.makedirs(output_dir, exist_ok=True)

data_by_date = defaultdict(list)
header = []

with open(input_file, 'r', encoding='utf-8') as f:
    reader = csv.reader(f)
    header = next(reader)
    for row in reader:
        if not row: continue
        # row[1] is timestamp, format: YYYY-MM-DD HH:MM:SS
        date_str = row[1].split(' ')[0]
        data_by_date[date_str].append(row)

for date_str, rows in data_by_date.items():
    out_path = os.path.join(output_dir, f"{date_str}.csv")
    with open(out_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {out_path}")
