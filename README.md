# Lucky 28 – Admin Import + Pro Streamlit Dashboard

The Django site keeps historical results in `lucky28.db`. Adding another day does
not replace earlier days. All history and analysis dates use UTC.

- Open `/days/` for the daily archive: result counts, Big/Small and Odd/Even
  totals, winners, prizes, and links to each day's history and analysis.
- Upload one or more dated CSV files at `/games/import/`. A file may contain
  multiple dates. Re-imports recognize saved results; invalid or conflicting
  rows cancel the entire upload. Historical imports do not send live alerts.
- The dashboard, `/history/`, and `/analysis/` open the latest saved day. Use
  the date selector or older/newer links to browse other days. Analysis uses
  every saved result for the selected day, in result timestamp order.
- Download a day's CSV from the archive or date selector. Downloads include
  game IDs and can be imported again. Analysis also accepts a date range.
- Use **Delete** beside a day in `/days/` to review its date and result count,
  then confirm removal. This permanently deletes that day's archived results
  and their associated signal history. You can download the CSV before deleting.

CSV format (timestamps are required):

```csv
result,timestamp,winners_count,prize_amount
19,2026-09-08 01:03:00,467,37006000
17,2026-09-07 23:59:00,450,30000000
```

Results without a winner timestamp cannot be assigned to an archived day.
Daily counts reflect the records saved so far; import additional history to
fill gaps. The legacy Game Results admin importer below feeds the Streamlit
table; use `/games/import/` for the Django dashboard and daily archive.

## 1. Create venv

```bash
cd lucky28_full_ui_single_venv
bash create_venv.sh
source venv/bin/activate
```

## 2. Django: migrate + admin

```bash
cd django_lucky28
python manage.py makemigrations gameapp
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open: http://127.0.0.1:8000/admin/

Use **Game Results → Import CSV** to load your `result` data.

## 3. Streamlit dashboard

New terminal:

```bash
cd lucky28_full_ui_single_venv
source venv/bin/activate
cd streamlit_lucky28
streamlit run app.py
```

The dashboard reads from the shared `lucky28.db` file.
