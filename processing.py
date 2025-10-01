# processing.py
import re
import numpy as np
import pandas as pd

# ----- Helper: find a column by regex patterns -----
def find_col(df, patterns):
    for c in df.columns:
        for pat in patterns:
            if re.search(pat, str(c), re.IGNORECASE):
                return c
    return None

def _promote_header_and_drop_first_three(raw_df: pd.DataFrame) -> pd.DataFrame:
    """
    1) Drop the first 3 rows from the ORIGINAL file.
    2) Use the next row as headers.
    """
    if raw_df is None or raw_df.empty:
        raise ValueError("Input spreadsheet is empty.")

    trimmed = raw_df.iloc[3:].reset_index(drop=True)
    if trimmed.shape[0] == 0:
        raise ValueError("No data remains after removing the first 3 rows.")

    new_header = trimmed.iloc[0].tolist()
    df = trimmed.iloc[1:].copy()
    df.columns = [str(x).strip() if pd.notna(x) else "" for x in new_header]
    df.columns = [re.sub(r"\s+", " ", c).strip() for c in df.columns]
    return df

def _split_name_to_first_last(full):
    """Split names. Prefer 'Last, First' if a comma is present; else fallback to whitespace split.
    Handles extra commas/suffixes safely and never over-unpacks.
    """
    if pd.isna(full):
        return pd.Series({"First Name": np.nan, "Last Name": np.nan})

    s = str(full).strip()
    if not s:
        return pd.Series({"First Name": "", "Last Name": ""})

    # Preferred form: "Last, First Middle ..." (only split once)
    if "," in s:
        parts = [p.strip() for p in s.split(",", 1)]
        if len(parts) == 2:
            last, rest = parts
        else:
            # Rare edge cases: treat the whole thing as "last", with empty "rest"
            last, rest = parts[0], ""
        first = rest.split()[0] if rest else ""
        return pd.Series({"First Name": first, "Last Name": last})

    # Fallback form: "First Middle Last"
    parts = s.split()
    if len(parts) == 1:
        return pd.Series({"First Name": parts[0], "Last Name": ""})
    return pd.Series({"First Name": parts[0], "Last Name": parts[-1]})

# ----- NEW: detect the available Shift Position Title options -----
def detect_shift_titles(raw_df: pd.DataFrame) -> list[str]:
    df = _promote_header_and_drop_first_three(raw_df)
    shift_col = find_col(df, [
        r"\bshift\s*position\s*title\b",
        r"\bshift.*title\b",
        r"\bposition\s*title\b",
        r"\bposition\b"
    ])
    if not shift_col:
        return []
    titles = (
        df[shift_col]
        .dropna()
        .astype(str)
        .str.strip()
        .replace("", np.nan)
        .dropna()
        .unique()
        .tolist()
    )
    titles = sorted(titles, key=lambda s: s.lower())
    return titles

def clean_and_filter(
    raw_df: pd.DataFrame,
    max_miles: float = 50.0,
    status_whitelist=None,
    include_resigned: bool = False,
    allowed_shift_titles: list[str] | None = None,
) -> pd.DataFrame:
    """
    Full cleaning pipeline:
    - Remove first 3 rows; promote next row as header
    - Phone cleaning & phone-based row drops
    - Dedupe by Employee Name
    - Distance filter <= max_miles
    - Status filter (with optional include_resigned)
    - ----- NEW: Shift Position Title filter (keep only selected titles)
    - Split Employee Name into First/Last
    """
    df = _promote_header_and_drop_first_three(raw_df)

    # Detect columns
    name_col   = find_col(df, [r"\bemployee\s*name\b", r"\bname\b"])
    phone_col  = find_col(df, [r"\bphone\b", r"\bmobile\b", r"\bcell\b"])
    miles_col  = find_col(df, [r"miles\s*from\s*location", r"\bdistance\b", r"\bmiles\b", r"\bmi\b"])
    status_col = find_col(df, [r"\bemployee\s*status\b", r"\bstatus\b"])
    shift_col  = find_col(df, [
        r"\bshift\s*position\s*title\b",
        r"\bshift.*title\b",
        r"\bposition\s*title\b",
        r"\bposition\b"
    ])

    if phone_col is None:
        raise ValueError("Could not find a phone column (e.g., 'Employee Phone').")
    if name_col is None:
        raise ValueError("Could not find an 'Employee Name' column.")

    # Phone cleaning
    df[phone_col] = df[phone_col].astype(str).str.replace(r"\D+", "", regex=True)
    df = df[~df[phone_col].isna()]
    df = df[df[phone_col].str.len() > 0]
    df = df[df[phone_col].str.replace(r"^0+$", "", regex=True).str.len() > 0]
    df = df[~df[phone_col].str.startswith("1")]

    # Dedupe by name
    df = df.drop_duplicates(subset=[name_col]).copy()

    # Distance filter
    if miles_col is not None:
        df[miles_col] = pd.to_numeric(df[miles_col], errors="coerce")
        df = df[df[miles_col] <= float(max_miles)]

    # Status filter
    if status_col is not None:
        if status_whitelist:
            allowed = set(s.lower() for s in status_whitelist)
            mask_whitelist = df[status_col].astype(str).str.lower().isin(allowed)
        else:
            mask_whitelist = pd.Series([True] * len(df), index=df.index)
        if include_resigned:
            mask_resigned = df[status_col].astype(str).str.strip().str.lower().eq("resigned")
            mask = mask_whitelist | mask_resigned
        else:
            mask = mask_whitelist
        df = df[mask]

    # ----- NEW: Shift Position Title filter
    if shift_col and allowed_shift_titles:
        allowed_norm = {s.strip().lower() for s in allowed_shift_titles if s and s.strip()}
        df = df[df[shift_col].astype(str).str.strip().str.lower().isin(allowed_norm)]

    # Split names
    split_df = df[name_col].apply(_split_name_to_first_last)
    insert_at = list(df.columns).index(name_col) + 1
    df.insert(insert_at, "First Name", split_df["First Name"])
    df.insert(insert_at + 1, "Last Name", split_df["Last Name"])

    # Nice column order
    ordered = [name_col, "First Name", "Last Name"]
    for col in [phone_col, miles_col, status_col, shift_col]:
        if col and col not in ordered:
            ordered.append(col)
    remaining = [c for c in df.columns if c not in ordered]
    df = df[ordered + remaining].reset_index(drop=True)
    return df
