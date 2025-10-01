# processing.py
import re
import numpy as np
import pandas as pd

# ----- Helper: find a column by regex patterns -----
def find_col(df, patterns):
    """
    Return the first column whose name matches any regex in `patterns` (case-insensitive).
    df columns should already be strings.
    """
    for c in df.columns:
        for pat in patterns:
            if re.search(pat, str(c), re.IGNORECASE):
                return c
    return None

def _promote_header_and_drop_first_three(raw_df: pd.DataFrame) -> pd.DataFrame:
    """
    1) Drop the first 3 rows (as requested) from the ORIGINAL file.
    2) Use the next row as headers.
    3) Return a DataFrame with clean string column names.
    """
    if raw_df is None or raw_df.empty:
        raise ValueError("Input spreadsheet is empty.")

    # 1) Remove first 3 rows from original
    #    (Works for both CSV and Excel reads with header=None)
    trimmed = raw_df.iloc[3:].reset_index(drop=True)

    if trimmed.shape[0] == 0:
        raise ValueError("No data remains after removing the first 3 rows.")

    # 2) Promote the first remaining row to header
    new_header = trimmed.iloc[0].tolist()
    df = trimmed.iloc[1:].copy()
    df.columns = [str(x).strip() if pd.notna(x) else "" for x in new_header]

    # Standardize column names: strip & collapse spaces
    df.columns = [re.sub(r"\s+", " ", c).strip() for c in df.columns]

    return df

def _split_name_to_first_last(full):
    """Split names. Prefer 'Last, First' if comma is present; else fallback to whitespace split."""
    if pd.isna(full):
        return pd.Series({"First Name": np.nan, "Last Name": np.nan})
    s = str(full).strip()
    if not s:
        return pd.Series({"First Name": "", "Last Name": ""})

    if "," in s:  # "Last, First Middle"
        parts = [p.strip() for p in s.split(",", 1)]
        last = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        first = rest.split()[0] if rest else ""
        return pd.Series({"First Name": first, "Last Name": last})

    # Fallback: "First Middle Last"
    parts = s.split()
    if len(parts) == 1:
        return pd.Series({"First Name": parts[0], "Last Name": ""})
    return pd.Series({"First Name": parts[0], "Last Name": parts[-1]})

def clean_and_filter(
    raw_df: pd.DataFrame,
    max_miles: float = 50.0,
    status_whitelist=None,
    include_resigned: bool = False
) -> pd.DataFrame:
    """
    Apply all requested rules:
    - Remove first 3 rows (done before header promotion)
    - Promote next row as header
    - Format phone (digits only), drop missing/zeros, drop starting-with-1
    - De-duplicate Employee Name
    - Filter <= max_miles
    - Filter by employee status (whitelist), with checkbox to include Resigned
    - Split Employee Name into First/Last
    - Output a clean DataFrame (ready to save as CSV)

    Parameters
    ----------
    raw_df : DataFrame read with header=None
    max_miles : float
    status_whitelist : list[str] | None
        If provided, keep only rows whose status is in this list (case-insensitive match).
    include_resigned : bool
        If True, include rows with status 'Resigned' in addition to the whitelist.
    """
    # Step A: Remove first 3 rows, promote header
    df = _promote_header_and_drop_first_three(raw_df)

    # Step B: Detect important columns
    name_col = find_col(df, [r"\bemployee\s*name\b", r"\bname\b"])
    phone_col = find_col(df, [r"\bphone\b", r"\bmobile\b", r"\bcell\b"])
    miles_col = find_col(df, [r"miles\s*from\s*location", r"\bdistance\b", r"\bmiles\b", r"\bmi\b"])
    status_col = find_col(df, [r"\bemployee\s*status\b", r"\bstatus\b"])

    # Step C: Clean phone numbers (digits only)
    if phone_col is None:
        raise ValueError("Could not find a phone column (e.g., 'Employee Phone').")

    df[phone_col] = df[phone_col].astype(str).str.replace(r"\D+", "", regex=True)

    # Step D: Remove rows with missing phone or all zeros
    df = df[~df[phone_col].isna()]
    df = df[df[phone_col].str.len() > 0]
    df = df[df[phone_col].str.replace(r"^0+$", "", regex=True).str.len() > 0]

    # Step E: Remove rows with phone numbers beginning with "1"
    df = df[~df[phone_col].str.startswith("1")]

    # Step F: Remove duplicate employee names
    if name_col is None:
        raise ValueError("Could not find an 'Employee Name' column.")
    df = df.drop_duplicates(subset=[name_col]).copy()

    # Step G: Filter by distance <= max_miles (if the column exists)
    if miles_col is not None:
        df[miles_col] = pd.to_numeric(df[miles_col], errors="coerce")
        df = df[df[miles_col] <= float(max_miles)]

    # Step H: Filter by status (if provided)
    if status_col is not None:
        if status_whitelist:
            # Build a case-insensitive boolean mask for listed statuses
            allowed = set(s.lower() for s in status_whitelist)
            mask_whitelist = df[status_col].astype(str).str.lower().isin(allowed)
        else:
            mask_whitelist = pd.Series([True] * len(df), index=df.index)

        # Include 'Resigned' if checked
        if include_resigned:
            mask_resigned = df[status_col].astype(str).str.strip().str.lower().eq("resigned")
            mask = mask_whitelist | mask_resigned
        else:
            mask = mask_whitelist

        df = df[mask]

    # Step I: Split names into "First Name" / "Last Name"
    split_df = df[name_col].apply(_split_name_to_first_last)
    insert_at = list(df.columns).index(name_col) + 1
    df.insert(insert_at, "First Name", split_df["First Name"])
    df.insert(insert_at + 1, "Last Name", split_df["Last Name"])

    # Optional: move key columns to the front (nice for CSV)
    ordered = [name_col, "First Name", "Last Name"]
    for col in [phone_col, miles_col, status_col]:
        if col and col not in ordered:
            ordered.append(col)

    remaining = [c for c in df.columns if c not in ordered]
    df = df[ordered + remaining]

    # Final tidy: reset index
    df = df.reset_index(drop=True)
    return df
