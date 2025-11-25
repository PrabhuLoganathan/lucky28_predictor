# Lucky 28 – Admin Import + Pro Streamlit Dashboard

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
