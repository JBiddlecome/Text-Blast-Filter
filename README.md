# Employee Filter App

A tiny Flask app that cleans and filters employee spreadsheets, then lets you download a CSV.

## What it does

- Removes the first 3 rows (title/junk rows).
- Promotes the next row to be the header row.
- Cleans phone numbers (keeps digits only).
- Drops rows with missing phone, all-zero phone (e.g., 0000000000), or phone that starts with "1".
- Removes duplicate employees by **Employee Name**.
- Filters to rows with **Miles From Location** <= your chosen number (default 50).
- Filters by **Employee Status** if you provide a list (comma-separated).
- Optional checkbox to **Include Resigned**.
- Splits **Employee Name** into **First Name** and **Last Name** (supports `Last, First` or `First Last`).

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
