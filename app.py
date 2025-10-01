# app.py
from flask import Flask, render_template, request, send_file, redirect, url_for, flash
import io
import pandas as pd
from processing import clean_and_filter

app = Flask(__name__)
app.secret_key = "change-this-to-a-long-random-string"

@app.route("/", methods=["GET"])
def index():
    return render_template("upload.html")

@app.route("/process", methods=["POST"])
def process():
    # 1) Validate inputs
    if "file" not in request.files:
        flash("Please upload a spreadsheet file.")
        return redirect(url_for("index"))

    f = request.files["file"]
    if not f or f.filename == "":
        flash("Please choose a spreadsheet to upload.")
        return redirect(url_for("index"))

    # Adjustable miles (default 50)
    try:
        max_miles = float(request.form.get("max_miles", "50"))
    except ValueError:
        flash("Max miles must be a number.")
        return redirect(url_for("index"))

    # Employee status filter
    # Accept a comma-separated list like: Active, Available, Inactive
    status_text = request.form.get("statuses", "").strip()
    statuses = [s.strip() for s in status_text.split(",") if s.strip()] if status_text else []

    # Checkbox to include Resigned
    include_resigned = request.form.get("include_resigned") == "on"

    # 2) Read the file into a DataFrame
    # We support xlsx/csv; if csv, read_csv; otherwise read_excel
    filename_lower = f.filename.lower()
    try:
        if filename_lower.endswith(".csv"):
            raw = pd.read_csv(f, header=None, dtype=str, keep_default_na=False)
        else:
            raw = pd.read_excel(f, header=None, dtype=str)
    except Exception as e:
        flash(f"Could not read file: {e}")
        return redirect(url_for("index"))

    # 3) Clean + filter
    try:
        df_out = clean_and_filter(
            raw_df=raw,
            max_miles=max_miles,
            status_whitelist=statuses,
            include_resigned=include_resigned
        )
    except Exception as e:
        flash(f"Processing error: {e}")
        return redirect(url_for("index"))

    # 4) Return as downloadable CSV
    output = io.StringIO()
    df_out.to_csv(output, index=False, encoding="utf-8-sig")
    output.seek(0)

    download_name = "employees-cleaned.csv"
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=download_name
    )

if __name__ == "__main__":
    # Run locally: python app.py, then open http://127.0.0.1:5000
    app.run(debug=True)
