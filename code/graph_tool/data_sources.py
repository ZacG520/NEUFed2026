"""
Loads data from FRED, Excel, or CSV into one standard shape:

    DataFrame, index = dates (named "Date"), one numeric column per series

Files from the web are messy, so load_file() tries to figure out the layout on
its own. It handles:
    - title/notes rows above the real header row
    - data on a sheet other than the first one
    - dates as real dates, "2023-01-01", "200801" (YYYYMM), "2023Q1",
      or split across two columns (Year + Quarter, Month + Year)
    - "na", ".", "#N/A", commas and % signs in the numbers
    - blank separator columns and repeated column names
    - "long" tables (Date, Series, Value) which get pivoted to one column per series
Anything it guesses can be overridden with the keyword arguments.
"""

import csv
import difflib
import os
import re
from pathlib import Path
from urllib.error import URLError

import pandas as pd

# FRED downloads fail on python.org Mac installs without this ("CERTIFICATE_VERIFY_FAILED").
# certifi ships an up-to-date certificate bundle; only used if the user hasn't set their own.
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except ImportError:
    pass


# Friendly names for FRED's "units" codes. The raw FRED codes also work.
FRED_UNITS = {
    "level": "lin",       # the data as published
    "change": "chg",      # change from previous period
    "yoy_change": "ch1",  # change from a year ago
    "mom": "pch",         # % change from previous period
    "yoy": "pc1",         # % change from a year ago
    "annualized": "pca",  # compounded annual rate of change
    "log": "log",         # natural log
}

MISSING_STRINGS = {"", "na", "n/a", "nan", "none", "null", "#n/a", "#value!", ".", "-", "--", "nd"}
DATE_WORDS = ("date", "year", "month", "quarter", "period", "time", "week", "day")
MONTH_NAMES = {m.lower(): i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

CODE_DIR = Path(__file__).resolve().parent.parent  # the repo's code/ folder


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def load_data(source, **kwargs) -> pd.DataFrame:
    """
    One entry point for everything. Decides FRED vs. file from `source`:
        load_data("CPIAUCSL, CPILFESL", units="yoy")      -> FRED
        load_data({"Headline": "CPIAUCSL"})                -> FRED, with labels
        load_data("data/gdp_contrib.csv")                  -> file
    kwargs are passed through to load_fred() or load_file(). Options that only apply to
    the other kind of source (e.g. units= for a file) are ignored, so a settings cell can
    list everything. columns= works for both.
    """
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    if isinstance(source, (str, Path)) and Path(str(source)).suffix.lower() in (".csv", ".txt", ".xlsx", ".xlsm", ".xls"):
        allowed = {"sheet", "header_row", "date_col", "columns", "start", "end", "verbose"}
        return load_file(source, **{k: v for k, v in kwargs.items() if k in allowed})

    allowed = {"start", "end", "units", "frequency", "aggregation", "api_key_path"}
    df = load_fred(source, **{k: v for k, v in kwargs.items() if k in allowed})
    if kwargs.get("columns") is not None:
        df = _select_columns(df, kwargs["columns"])
    return df


def load_fred(series, start=None, end=None, units="level", frequency=None,
              aggregation="avg", api_key_path=None) -> pd.DataFrame:
    """
    Downloads one or more FRED series into a single table.

    Parameters:
        series: "CPIAUCSL", "CPIAUCSL, CPILFESL", a list of IDs, or a dict
                {"Label to show": "SERIES_ID"} to name the lines yourself.
        start, end: "YYYY-MM-DD" strings or dates (default: all available data)
        units: one of FRED_UNITS (e.g. "yoy") or a raw FRED code (e.g. "pc1").
               Pass a dict {label_or_id: units} to use different units per series.
        frequency: None (native), or "m", "q", "a", "w", "d" to convert
        aggregation: how to convert frequency: "avg", "sum", or "eop" (end of period)
        api_key_path: defaults to fred_api_key.txt in the repo root

    Series with different frequencies are kept on one table (outer join), with blanks
    where a series has no observation.
    """
    from fredapi import Fred

    labels_to_ids = _normalize_series_arg(series)
    fred = Fred(api_key_file=str(api_key_path or _find_api_key()))

    columns = []
    for label, series_id in labels_to_ids.items():
        unit = units.get(label, units.get(series_id, "level")) if isinstance(units, dict) else units
        unit_code = FRED_UNITS.get(str(unit).lower(), str(unit).lower())
        if unit_code not in set(FRED_UNITS.values()) | {"cch", "cca", "cap"}:
            raise ValueError(f"Units {unit!r} not recognized. Use one of: {', '.join(FRED_UNITS)}")
        params = {"units": unit_code}
        if frequency:
            params.update(frequency=frequency, aggregation_method=aggregation)
        try:
            srs = fred.get_series(series_id, observation_start=start, observation_end=end, **params)
        except ValueError as err:
            reason = re.sub(r"\s+", " ", str(err)).rstrip(". ")
            raise ValueError(f"FRED couldn't load '{series_id}': {reason}. "
                             "Check the ID on fred.stlouisfed.org (it's the code at the end of the URL).") from None
        except URLError as err:
            raise ConnectionError(f"Couldn't reach FRED ({err.reason}). Check your internet connection. "
                                  "If the error mentions certificates, run: pip install -r requirements.txt") from None
        columns.append(srs.rename(label))

    df = pd.concat(columns, axis=1, join="outer")
    df.index = pd.to_datetime(df.index)
    df.index.name = "Date"
    return df.dropna(how="all")


def load_file(path, sheet=None, header_row=None, date_col=None, columns=None,
              start=None, end=None, verbose=True) -> pd.DataFrame:
    """
    Reads a CSV or Excel file and cleans it into the standard shape.

    Parameters:
        path: file path. Relative paths are checked against the current folder,
              then code/, then code/data/.
        sheet: Excel sheet name or number. Default: first sheet that contains data.
        header_row: row number (0 = first row) holding the column names. Default: auto.
        date_col: column name holding the dates, or a list of two names for split
                  dates like ["Year", "Quarter"]. Default: auto.
        columns: which series to keep. A list of names, or a dict {name in file: new label}.
                 Matching ignores capitalization/extra spaces and suggests close names on typos.
        start, end: optional date limits, "YYYY-MM-DD"
        verbose: print what was detected (sheet, header row, date column)
    """
    path = _resolve_path(path)
    ext = path.suffix.lower()

    if ext in (".csv", ".txt"):
        raw = _read_csv_raw(path)
        df, notes = _clean_table(raw, header_row, date_col)
        notes.insert(0, f"Read {path.name}")
    elif ext in (".xlsx", ".xlsm", ".xls"):
        df, notes = _read_excel(path, sheet, header_row, date_col)
    else:
        raise ValueError(f"Don't know how to read '{ext}' files. Use .csv, .xlsx, or .xls.")

    if columns is not None:
        df = _select_columns(df, columns)
    if start is not None or end is not None:
        df = df.loc[start:end]

    if verbose:
        for note in notes:
            print("  " + note)
    return df


def preview(df: pd.DataFrame) -> None:
    """Prints a quick summary: date range, frequency, and each column's latest value."""
    freq = _guess_frequency(df.index)
    print(f"{len(df)} rows, {df.index.min():%Y-%m-%d} to {df.index.max():%Y-%m-%d} ({freq})")
    print(f"{len(df.columns)} series:")
    for col in df.columns:
        last = df[col].dropna()
        latest = f"{last.iloc[-1]:,.2f} on {last.index[-1]:%Y-%m-%d}" if len(last) else "no data"
        print(f"  - {col!r}: latest {latest}")


# ---------------------------------------------------------------------------
# Reading raw files
# ---------------------------------------------------------------------------

def _resolve_path(path) -> Path:
    path = Path(path).expanduser()
    for candidate in (path, CODE_DIR / path, CODE_DIR / "data" / path):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Couldn't find '{path}'. Put it in code/data/ or give the full path.")


def _read_csv_raw(path: Path) -> pd.DataFrame:
    """Reads every row as text, even when rows have different lengths (title lines etc.)."""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:5000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(text.splitlines(), dialect))
    width = max((len(r) for r in rows), default=0)
    return pd.DataFrame([r + [""] * (width - len(r)) for r in rows], dtype=object)


def _read_excel(path, sheet, header_row, date_col):
    try:
        book = pd.ExcelFile(path)
    except Exception as err:
        raise ValueError(f"Couldn't open {path.name}: {err}") from None

    if not book.sheet_names:
        raise ValueError(
            f"{path.name} is saved in Excel's 'Strict Open XML' format, which Python can't read. "
            "Open it in Excel, File > Save As, and choose 'Excel Workbook (.xlsx)'.")

    if sheet is not None:
        sheets = [book.sheet_names[sheet] if isinstance(sheet, int) else sheet]
    else:
        sheets = book.sheet_names

    errors = []
    for name in sheets:
        raw = pd.read_excel(book, sheet_name=name, header=None, dtype=object)
        try:
            df, notes = _clean_table(raw, header_row, date_col)
        except ValueError as err:
            errors.append(f"'{name}': {err}")
            continue
        notes.insert(0, f"Read {path.name}, sheet '{name}'")
        others = [s for s in book.sheet_names if s != name]
        if sheet is None and others:
            shown = others if len(others) <= 8 else others[:8] + [f"... {len(others) - 8} more"]
            notes.insert(1, f"Other sheets (use sheet=...): {shown}")
        return df, notes

    raise ValueError(f"No usable data found in {path.name}.\n  " + "\n  ".join(errors))


# ---------------------------------------------------------------------------
# Cleaning: raw grid of cells -> standard table
# ---------------------------------------------------------------------------

def _clean_table(raw: pd.DataFrame, header_row=None, date_col=None):
    """Turns a raw grid of cells into the standard table. Returns (df, notes)."""
    notes = []
    raw = raw.dropna(how="all", axis=0).dropna(how="all", axis=1)
    raw = raw.loc[:, ~raw.map(_is_missing).all()]  # drop columns that are only "" / "na"
    if raw.empty:
        raise ValueError("sheet is empty")

    # 1. Find the header row and the first row of data
    if header_row is None:
        header_pos = _find_header_row(raw)
    else:
        header_pos = raw.index.get_loc(header_row) if header_row in raw.index else header_row
    if header_pos is None:
        names = [f"Column {i + 1}" for i in range(raw.shape[1])]
        body = raw
        notes.append("No header row found; columns are named Column 1, Column 2, ...")
    else:
        names = _make_column_names(raw.iloc[header_pos].tolist())
        body = raw.iloc[header_pos + 1:]
        notes.append(f"Header row: row {raw.index[header_pos] + 1} of the file")
    body = body.set_axis(names, axis=1).reset_index(drop=True)
    # Rows with only one filled cell are notes/footnotes ("Source: BLS", "p = preliminary")
    body = body[body.map(lambda v: not _is_missing(v)).sum(axis=1) >= 2].reset_index(drop=True)

    # 2. Find the dates
    dates, used_cols = _find_dates(body, date_col)
    notes.append(f"Dates from: {' + '.join(repr(c) for c in used_cols)}")
    body = body.drop(columns=used_cols)
    keep = dates.notna()
    body, dates = body[keep], dates[keep]

    # 3. Long table (Date, Series, Value)? Pivot to one column per series
    numeric = body.apply(_to_number)
    category = _find_category_column(body, numeric, dates)
    if category is not None:
        value_cols = [c for c in numeric.columns if c != category and numeric[c].notna().any()]
        wide = numeric[value_cols].assign(_date=dates.values, _cat=body[category].astype(str).str.strip().values)
        df = wide.pivot_table(index="_date", columns="_cat", values=value_cols, aggfunc="last")
        df.columns = [c[1] if len(value_cols) == 1 else f"{c[1]} - {c[0]}" for c in df.columns]
        notes.append(f"Long format detected: made one column per value of {category!r}")
    else:
        # 4. Keep only columns that actually contain numbers
        df = numeric.loc[:, numeric.notna().mean() > 0.5]
        df.index = pd.DatetimeIndex(dates.values)
        dropped = [c for c in numeric.columns if c not in df.columns]
        if dropped:
            notes.append(f"Skipped non-numeric columns: {dropped}")

    if df.empty or df.shape[1] == 0:
        raise ValueError("found dates but no numeric columns")

    df.index.name = "Date"
    df = df.sort_index().dropna(how="all")
    if df.index.duplicated().any():
        notes.append("Warning: some dates appear more than once (kept all rows)")
    notes.append(f"Series: {list(df.columns)}")
    return df, notes


def _find_header_row(raw: pd.DataFrame):
    """
    First "data row" = a row where most filled cells are numbers or dates (at least 2).
    Header = closest row above it with at least 2 filled cells.
    """
    kinds = raw.map(_cell_kind)
    first_data = None
    for pos in range(len(raw)):
        row = kinds.iloc[pos]
        filled = (row != "empty").sum()
        values = (row == "value").sum()
        if values >= 2 and values >= 0.5 * filled:
            first_data = pos
            break
    if first_data is None:
        raise ValueError("no rows of numbers found")
    for pos in range(first_data - 1, -1, -1):
        if (kinds.iloc[pos] != "empty").sum() >= 2:
            return pos
    return None


def _make_column_names(cells):
    """
    Cleans header cells into unique names. Repeated names get their "parent" as a
    prefix, using indentation if the file has it (e.g. "    Goods" under "Exports"
    becomes "Exports - Goods"), otherwise the nearest earlier non-repeated name.
    """
    raw_names = ["" if _is_missing(c) else str(c).replace("\n", " ").rstrip() for c in cells]
    indents = [len(n) - len(n.lstrip()) for n in raw_names]
    names = [re.sub(r"\s+", " ", n).strip() for n in raw_names]
    counts = pd.Series([n for n in names if n]).value_counts()
    has_indents = any(indents)

    result = []
    for i, name in enumerate(names):
        if not name:
            result.append(f"Unnamed {i + 1}")
            continue
        if counts[name] > 1:
            parent = None
            for j in range(i - 1, -1, -1):
                if not names[j]:
                    continue
                if (has_indents and indents[j] < indents[i]) or (not has_indents and counts[names[j]] == 1):
                    parent = names[j]
                    break
            if parent:
                name = f"{parent} - {name}"
        result.append(name)

    # Anything still repeated gets (2), (3), ...
    seen = {}
    for i, name in enumerate(result):
        if name in seen:
            seen[name] += 1
            result[i] = f"{name} ({seen[name]})"
        else:
            seen[name] = 1
    return result


def _find_dates(body: pd.DataFrame, date_col=None):
    """Returns (Series of Timestamps, [columns used]). Tries split dates, then single columns."""
    if date_col is not None:
        cols = [date_col] if isinstance(date_col, str) else list(date_col)
        cols = [_match_column(c, body.columns) for c in cols]
        dates = _combine_split_dates(body, cols) if len(cols) == 2 else _parse_dates(body[cols[0]])
        if dates.notna().mean() < 0.5:
            raise ValueError(f"Couldn't read dates from {cols}. Sample values: {body[cols[0]].head(3).tolist()}")
        return dates, cols

    # Split dates: a year column next to a quarter/month column
    for i, col in enumerate(body.columns):
        if not _is_year_column(body[col]):
            continue
        for j in (i + 1, i - 1):
            if 0 <= j < len(body.columns) and _period_kind(body.iloc[:, j]) is not None:
                cols = [col, body.columns[j]]
                return _combine_split_dates(body, cols), cols

    # Single date column: columns named like dates first, then left to right
    order = sorted(body.columns, key=lambda c: (not any(w in str(c).lower() for w in DATE_WORDS),
                                                list(body.columns).index(c)))
    for col in order:
        dates = _parse_dates(body[col])
        filled = body[col].map(lambda v: not _is_missing(v)).sum()
        if filled and dates.notna().sum() >= 0.8 * filled:
            return dates, [col]

    raise ValueError("couldn't find a date column (pass date_col=... to choose one)")


def _find_category_column(body, numeric, dates):
    """For long tables: a text column with a few repeating labels, when dates repeat too."""
    if not dates.duplicated().any():
        return None
    for col in body.columns:
        text = body[col][numeric[col].isna() & body[col].map(lambda v: not _is_missing(v))]
        if len(text) >= 0.8 * len(body) and 1 < text.nunique() <= 50:
            return col
    return None


def _select_columns(df, columns):
    """Keeps (and optionally renames) columns, forgiving capitalization/spacing differences."""
    rename = columns if isinstance(columns, dict) else {c: c for c in columns}
    picked = {}
    for wanted, label in rename.items():
        picked[_match_column(wanted, df.columns)] = label
    return df[list(picked)].rename(columns=picked)


def _match_column(wanted, available):
    """Finds `wanted` in `available`, ignoring case and spacing. Suggests close matches on failure."""
    def simplify(s):
        return re.sub(r"[\s_]+", " ", str(s)).strip().lower()
    lookup = {simplify(c): c for c in available}
    if simplify(wanted) in lookup:
        return lookup[simplify(wanted)]
    close = difflib.get_close_matches(simplify(wanted), list(lookup), n=3, cutoff=0.5)
    hint = f" Did you mean: {[lookup[c] for c in close]}?" if close else ""
    raise KeyError(f"No column named {wanted!r}.{hint}\n  Available: {list(available)}")


# ---------------------------------------------------------------------------
# Cell-level helpers
# ---------------------------------------------------------------------------

def _is_missing(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and v != v:  # NaN
        return True
    if v is pd.NaT:
        return True
    return isinstance(v, str) and v.strip().lower() in MISSING_STRINGS


def _to_float(v):
    """A single cell -> float, or None. Handles '1,234', '3.5%', '$10', '(2.1)' for negatives."""
    if _is_missing(v) or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return None
    s = v.strip().replace(",", "").replace("$", "").replace("%", "")
    if re.fullmatch(r"\(\s*[\d.]+\s*\)", s):  # accounting negatives: (2.1)
        s = "-" + s.strip("() ")
    try:
        return float(s)
    except ValueError:
        return None


def _to_number(col: pd.Series) -> pd.Series:
    return pd.to_numeric(col.map(_to_float), errors="coerce").astype(float)


def _cell_kind(v) -> str:
    if _is_missing(v):
        return "empty"
    if _to_float(v) is not None or _parse_date_value(v) is not None:
        return "value"
    return "text"


def _parse_date_value(v):
    """One cell -> Timestamp, or None. Deliberately strict so numbers like 3.5 aren't read as dates."""
    if _is_missing(v):
        return None
    if isinstance(v, pd.Timestamp) or hasattr(v, "year") and hasattr(v, "month"):
        return pd.Timestamp(v)

    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if v != int(v):
            return None
        s = str(int(v))
    else:
        s = str(v).strip()

    try:
        if re.fullmatch(r"\d{8}", s):                                 # 20230115
            return pd.Timestamp(year=int(s[:4]), month=int(s[4:6]), day=int(s[6:]))
        if re.fullmatch(r"\d{6}", s):                                 # 202301
            return pd.Timestamp(year=int(s[:4]), month=int(s[4:]), day=1)
        if re.fullmatch(r"\d{4}", s) and 1800 <= int(s) <= 2200:      # 2023
            return pd.Timestamp(year=int(s), month=1, day=1)
        m = re.fullmatch(r"(\d{4})\s*[-:/ ]?\s*Q([1-4])", s, re.I)    # 2023Q1, 2023-Q1
        if m:
            return pd.Timestamp(year=int(m[1]), month=3 * int(m[2]) - 2, day=1)
        m = re.fullmatch(r"Q([1-4])\s*[-:/ ]?\s*(\d{4})", s, re.I)    # Q1 2023
        if m:
            return pd.Timestamp(year=int(m[2]), month=3 * int(m[1]) - 2, day=1)
        m = re.fullmatch(r"(\d{4})M(\d{1,2})", s, re.I)               # 2023M01
        if m:
            return pd.Timestamp(year=int(m[1]), month=int(m[2]), day=1)
        if (re.match(r"\d{4}[-/.]\d{1,2}([-/.]\d{1,2})?([ T].*)?$", s)       # 2023-01-15, 2023-01
                or re.fullmatch(r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", s)          # 1/15/2023
                or re.fullmatch(r"[A-Za-z]{3,9}\.?[\s\-,]*\d{1,2}?,?\s*\d{2,4}", s)  # Jan 2023, January 15, 2023
                or re.fullmatch(r"\d{1,2}[\s\-][A-Za-z]{3,9}[\s\-]\d{2,4}", s)):     # 15-Jan-2023
            if re.fullmatch(r"\d{4}[-/.]\d{1,2}", s):
                s += "-01"
            return pd.Timestamp(pd.to_datetime(s))
    except (ValueError, OverflowError):
        return None
    return None


def _parse_dates(col: pd.Series) -> pd.Series:
    return pd.to_datetime(col.map(_parse_date_value), errors="coerce")


def _is_year_column(col: pd.Series) -> bool:
    nums = _to_number(col).dropna()
    return len(nums) > 0 and len(nums) >= 0.8 * col.map(lambda v: not _is_missing(v)).sum() \
        and (nums == nums.round()).all() and nums.between(1800, 2200).all()


def _period_kind(col: pd.Series):
    """'quarter' if values look like Q1-Q4, 'month' if 1-12 or month names, else None."""
    vals = col[col.map(lambda v: not _is_missing(v))].astype(str).str.strip()
    if vals.empty:
        return None
    if vals.str.fullmatch(r"[Qq][1-4]").mean() > 0.9:
        return "quarter"
    if vals.str.lower().str[:3].isin(list(MONTH_NAMES)).mean() > 0.9:
        return "month"
    nums = _to_number(vals)
    if nums.notna().mean() > 0.9 and nums.dropna().between(1, 12).all() and (nums.dropna() % 1 == 0).all():
        return "month"
    return None


def _combine_split_dates(body, cols) -> pd.Series:
    """Year column + period column -> dates. Works in either order."""
    a, b = cols
    year_col, period_col = (a, b) if _is_year_column(body[a]) else (b, a)
    years = _to_number(body[year_col])
    periods = body[period_col].astype(str).str.strip()
    if _period_kind(body[period_col]) == "quarter":
        months = periods.str[-1].astype(int) * 3 - 2
    else:
        months = periods.str.lower().str[:3].map(MONTH_NAMES)
        months = months.fillna(_to_number(periods))
    return pd.to_datetime(pd.DataFrame({"year": years, "month": months, "day": 1}), errors="coerce")


def _guess_frequency(index: pd.DatetimeIndex) -> str:
    if len(index) < 3:
        return "unknown frequency"
    days = pd.Series(index).diff().dt.days.median()
    for limit, name in ((1.5, "daily"), (8, "weekly"), (35, "monthly"), (100, "quarterly"), (400, "annual")):
        if days <= limit:
            return name
    return "irregular"


def _find_api_key() -> Path:
    """Looks for fred_api_key.txt in this folder and every folder above it."""
    for folder in [CODE_DIR, *CODE_DIR.parents]:
        if (folder / "fred_api_key.txt").exists():
            return folder / "fred_api_key.txt"
    raise FileNotFoundError("Couldn't find fred_api_key.txt. See the README for how to get a FRED API key.")


def _normalize_series_arg(series) -> dict:
    """Accepts 'A, B', ['A', 'B'], or {'Label': 'A'} and returns {label: series_id}."""
    if isinstance(series, dict):
        return {str(k): str(v).strip().upper() for k, v in series.items()}
    if isinstance(series, str):
        series = re.split(r"[,\s]+", series.strip())
    ids = [str(s).strip().upper() for s in series if str(s).strip()]
    if not ids:
        raise ValueError("No FRED series IDs given.")
    return {i: i for i in ids}
