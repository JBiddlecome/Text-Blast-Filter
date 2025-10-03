# app.py
import os
import io
import uuid
import re
from pathlib import Path
from flask import Flask, render_template, request, send_file, redirect, url_for, flash
import pandas as pd
from werkzeug.utils import secure_filename

from processing import clean_and_filter, detect_shift_titles

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-in-prod")

# Temp upload directory (Render supports /tmp)
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/tmp/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

@app.route("/", methods=["GET"])
def index():
    return render_template("upload.html")

# NEW: Step 1 - detect available Shift Position Titles
@app.route("/detect", methods=["POST"])
def detect():
    if "file" not in request.files:
        flash("Please upload a spreadsheet file.")
        return redirect(url_for("index"))

    f = request.files["file"]
    if not f or f.filename == "":
        flash("Please choose a spreadsheet to upload.")
        return redirect(url_for("index"))

    filename = secure_filename(f.filename)
    ext = Path(filename).suffix.lower()
    if ext not in [".xlsx", ".csv"]:
        flash("Please upload a .xlsx or .csv file.")
        return redirect(url_for("index"))

    # Save the raw upload to a temp file so we can reuse it on the next step
    temp_id = str(uuid.uuid4())
    temp_path = UPLOAD_DIR / f"{temp_id}{ext}"
    f.save(temp_path)

    # Load with header=None so processing can promote headers after dropping 3 rows
    try:
        if ext == ".csv":
            raw = pd.read_csv(temp_path, header=None, dtype=str, keep_default_na=False)
        else:
            raw = pd.read_excel(temp_path, header=None, dtype=str)
    except Exception as e:
        flash(f"Could not read file: {e}")
        return redirect(url_for("index"))

    # Detect titles
    try:
        titles = detect_shift_titles(raw)
    except Exception as e:
        flash(f"Error while scanning titles: {e}")
        return redirect(url_for("index"))

    return render_template(
        "select.html",
        temp_id=temp_id,
        ext=ext,
        shift_titles=titles  # may be []
    )

# Step 2 - run full processing with chosen titles
@app.route("/process", methods=["POST"])
def process():
    temp_id = request.form.get("temp_id")
    ext = request.form.get("ext", ".xlsx")
    if not temp_id:
        flash("Missing uploaded file reference. Please upload again.")
        return redirect(url_for("index"))

    temp_path = UPLOAD_DIR / f"{temp_id}{ext}"
    if not temp_path.exists():
        flash("Uploaded file not found. Please upload again.")
        return redirect(url_for("index"))

    # Inputs
    try:
        max_miles = float(request.form.get("max_miles", "50"))
    except ValueError:
        flash("Max miles must be a number.")
        return redirect(url_for("index"))

    statuses_text = request.form.get("statuses", "").strip()
    statuses = [s.strip() for s in statuses_text.split(",") if s.strip()] if statuses_text else []
    include_resigned = request.form.get("include_resigned") == "on"

    # Selected shift titles (list of strings)
    allowed_shift_titles = request.form.getlist("shift_titles")
    if allowed_shift_titles is None:
        allowed_shift_titles = []

    # Load raw again
    try:
        if ext == ".csv":
            raw = pd.read_csv(temp_path, header=None, dtype=str, keep_default_na=False)
        else:
            raw = pd.read_excel(temp_path, header=None, dtype=str)
    except Exception as e:
        flash(f"Could not read uploaded file: {e}")
        return redirect(url_for("index"))

    # Clean + filter
    try:
        df_out = clean_and_filter(
            raw_df=raw,
            max_miles=max_miles,
            status_whitelist=statuses,
            include_resigned=include_resigned,
            allowed_shift_titles=allowed_shift_titles
        )
    except Exception as e:
        flash(f"Processing error: {e}")
        return redirect(url_for("index"))

    # Return CSV
    output = io.StringIO()
    df_out.to_csv(output, index=False, encoding="utf-8-sig")
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="employees-cleaned.csv"
    )

# --- Recruiting Employee Export List (new feature) ---------------------------

def _rx_digits_only(series: pd.Series) -> pd.Series:
    """Keep digits only in a phone column."""
    return series.fillna("").astype(str).apply(lambda x: re.sub(r"\D", "", x))

def _normalize_list(raw: str):
    """Split by comma/newline/semicolon, lowercase, trim; empty -> []"""
    if not raw:
        return []
    parts = re.split(r"[,\n;]+", raw)
    return [p.strip().lower() for p in parts if p.strip()]

def _contains_any(hay: str, needles):
    """Case-insensitive substring match: True if any needle in hay."""
    hay = (hay or "").lower()
    return any(n in hay for n in needles) if needles else True

@app.route("/recruiting-export", methods=["GET", "POST"])
def recruiting_export():
    if request.method == "GET":
        return render_template("recruiting_export.html")

    # POST: handle upload + filters
    f = request.files.get("csv_file")
    if not f or f.filename == "":
        flash("Please choose a CSV/XLSX file to upload.")
        return redirect(url_for("recruiting_export"))

    filename = secure_filename(f.filename)
    ext = Path(filename).suffix.lower()

    # Read uploaded file to DataFrame
    try:
        if ext == ".csv":
            df = pd.read_csv(f)
        else:
            # fall back to excel
            f.stream.seek(0)
            df = pd.read_excel(f)
    except Exception as e:
        flash(f"Could not read file: {e}")
        return redirect(url_for("recruiting_export"))

    # Required columns
    required = ["Status", "County", "Positions", "Mobile"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        flash(f"Missing required column(s): {', '.join(missing)}")
        return redirect(url_for("recruiting_export"))

    # Inputs
    status_needles   = set(_normalize_list(request.form.get("status_list", "")))    # exact match
    county_needles   = set(_normalize_list(request.form.get("county_list", "")))    # substring
    positions_needles = _normalize_list(request.form.get("positions_text", ""))     # substring

    # Clean Mobile -> digits only
    df["Mobile"] = _rx_digits_only(df["Mobile"])

    # Remove rows with Mobile empty OR starting with '1'
    df = df[df["Mobile"].str.len() > 0]
    df = df[~df["Mobile"].str.startswith("1")]

    # Apply filters
    if status_needles:
        df = df[df["Status"].fillna("").str.lower().isin(status_needles)]

    if county_needles:
        df = df[df["County"].fillna("").str.lower().apply(
            lambda v: any(n in v for n in county_needles)
        )]

    if positions_needles:
        df = df[df["Positions"].fillna("").str.lower().apply(
            lambda v: _contains_any(v, positions_needles)
        )]

    # Output CSV
    output = io.StringIO()
    df.to_csv(output, index=False)
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="recruiting-employee-export.csv"
    )


# (Nice-to-have) Healthcheck for Render
@app.route("/healthz")
def healthz():
    return "ok", 200

if __name__ == "__main__":
    # Bind to the port Render provides if running there, else default to 5000 locally
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
