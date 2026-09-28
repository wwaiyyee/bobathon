from __future__ import annotations

import hashlib
import io
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import chardet
import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from slugify import slugify

from models.core import (
    ColumnRole,
    DataDictionaryEntry,
    DatasetVersion,
    TransformationStep,
)

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

PARQUET_DIR = os.getenv("PARQUET_DIR", "data/parquet")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def ingest_file(
    dataset_id: str,
    file_bytes: bytes,
    filename: str,
) -> Tuple[DatasetVersion, List[TransformationStep], List[DataDictionaryEntry]]:
    """
    Parse *file_bytes* (CSV or Excel) into a normalised Parquet file.

    Returns (DatasetVersion, transformation_log, dictionary_proposals).
    """
    steps: List[TransformationStep] = []
    ext = Path(filename).suffix.lower()

    if ext in (".xlsx", ".xls", ".xlsm"):
        df, sheet_steps = _read_excel(file_bytes, filename)
        steps.extend(sheet_steps)
    else:
        df, csv_steps = _read_csv(file_bytes, filename)
        steps.extend(csv_steps)

    df, clean_steps = _clean_dataframe(df)
    steps.extend(clean_steps)

    version = _to_parquet(dataset_id, file_bytes, filename, df)
    dictionary = _propose_dictionary(df)

    return version, steps, dictionary


# ---------------------------------------------------------------------------
# CSV reading
# ---------------------------------------------------------------------------


def _read_csv(
    file_bytes: bytes, filename: str
) -> Tuple[pd.DataFrame, List[TransformationStep]]:
    steps: List[TransformationStep] = []

    # Encoding detection
    detected = chardet.detect(file_bytes)
    encoding = detected.get("encoding") or "utf-8"
    steps.append(
        TransformationStep(
            step_type="encoding_detected",
            description=f"Detected encoding: {encoding} (confidence {detected.get('confidence', 0):.0%})",
            rows_affected=0,
        )
    )

    text = file_bytes.decode(encoding, errors="replace")

    # Delimiter detection
    sample = "\n".join(text.splitlines()[:5])
    delimiter = _detect_delimiter(sample)
    steps.append(
        TransformationStep(
            step_type="delimiter_detected",
            description=f"Detected delimiter: {repr(delimiter)}",
            rows_affected=0,
        )
    )

    df = pd.read_csv(
        io.StringIO(text),
        sep=delimiter,
        dtype=str,
        keep_default_na=False,
    )
    return df, steps


def _detect_delimiter(sample: str) -> str:
    counts = {d: sample.count(d) for d in [",", ";", "|", "\t"]}
    return max(counts, key=counts.get)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Excel reading
# ---------------------------------------------------------------------------


def _read_excel(
    file_bytes: bytes, filename: str
) -> Tuple[pd.DataFrame, List[TransformationStep]]:
    steps: List[TransformationStep] = []
    xl = pd.ExcelFile(io.BytesIO(file_bytes))
    sheet_names = xl.sheet_names

    steps.append(
        TransformationStep(
            step_type="excel_sheets_detected",
            description=f"Sheets found: {sheet_names}. Using first sheet: {sheet_names[0]}",
            rows_affected=0,
        )
    )

    # Read first sheet without header to detect header row
    raw = xl.parse(sheet_names[0], header=None, dtype=str, keep_default_na=False)

    header_row = _detect_header_row(raw)
    if header_row > 0:
        steps.append(
            TransformationStep(
                step_type="header_row_detected",
                description=f"Skipped {header_row} title row(s) above data header.",
                rows_affected=header_row,
                requires_approval=False,
            )
        )

    df = xl.parse(sheet_names[0], header=header_row, dtype=str, keep_default_na=False)

    # Flatten merged cells: forward-fill column headers that are NaN (merged)
    df.columns = [
        str(c) if not str(c).startswith("Unnamed") else ""
        for c in df.columns
    ]
    # Fill empty column names with previous name (merged header pattern)
    filled_cols: List[str] = []
    last = ""
    for col in df.columns:
        if col:
            last = col
            filled_cols.append(col)
        else:
            filled_cols.append(last)
    df.columns = pd.Index(filled_cols)

    return df, steps


def _detect_header_row(raw: pd.DataFrame) -> int:
    """Return row index of the actual header (first row with >50% non-empty cells)."""
    for i, row in raw.iterrows():
        non_empty = (row.astype(str).str.strip() != "").sum()
        if non_empty > len(row) * 0.5:
            return int(i)  # type: ignore[arg-type]
    return 0


# ---------------------------------------------------------------------------
# DataFrame cleaning
# ---------------------------------------------------------------------------


def _clean_dataframe(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[TransformationStep]]:
    steps: List[TransformationStep] = []

    original_rows = len(df)

    # Strip empty rows/cols
    df = df.dropna(how="all")
    df = df.loc[:, df.notna().any()]
    df.columns = [str(c).strip() for c in df.columns]

    # Remove rows where all values are empty strings
    df = df[~(df.map(lambda x: str(x).strip() == "").all(axis=1))]

    empty_dropped = original_rows - len(df)
    if empty_dropped:
        steps.append(
            TransformationStep(
                step_type="empty_rows_removed",
                description=f"Removed {empty_dropped} fully empty rows.",
                rows_affected=empty_dropped,
            )
        )

    # Detect and flag total/subtotal rows
    total_mask = _detect_total_rows(df)
    total_count = total_mask.sum()
    if total_count:
        steps.append(
            TransformationStep(
                step_type="total_rows_detected",
                description=f"Detected {total_count} total/subtotal rows. Remove them to avoid double-counting.",
                rows_affected=int(total_count),
                requires_approval=True,
            )
        )
        df = df[~total_mask]

    # Detect wide/pivot format (flag only)
    if _looks_like_pivot(df):
        steps.append(
            TransformationStep(
                step_type="wide_format_detected",
                description="Dataset appears to be in wide/pivot format. Consider unpivoting for analysis.",
                rows_affected=0,
                requires_approval=False,
            )
        )

    # Locale-aware numeric parsing and date parsing
    df, numeric_steps = _parse_numeric_columns(df)
    steps.extend(numeric_steps)

    df, date_steps = _parse_date_columns(df)
    steps.extend(date_steps)

    # Duplicate row flagging
    dup_count = df.duplicated().sum()
    if dup_count:
        steps.append(
            TransformationStep(
                step_type="duplicate_rows_detected",
                description=f"{dup_count} duplicate rows detected.",
                rows_affected=int(dup_count),
                requires_approval=True,
            )
        )

    df = df.reset_index(drop=True)
    return df, steps


def _detect_total_rows(df: pd.DataFrame) -> "pd.Series[bool]":
    total_pattern = re.compile(r"^\s*(total|subtotal|grand total|sum)\s*$", re.IGNORECASE)
    mask = df.apply(lambda row: row.astype(str).str.match(total_pattern).any(), axis=1)
    return mask


def _looks_like_pivot(df: pd.DataFrame) -> bool:
    """Heuristic: many numeric-looking columns with year/month-like headers."""
    year_like = sum(1 for c in df.columns if re.match(r"^\d{4}$", str(c).strip()))
    month_like = sum(
        1
        for c in df.columns
        if re.match(
            r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
            str(c).strip(),
            re.IGNORECASE,
        )
    )
    return year_like >= 3 or month_like >= 3


def _parse_numeric_columns(
    df: pd.DataFrame,
) -> Tuple[pd.DataFrame, List[TransformationStep]]:
    steps: List[TransformationStep] = []
    for col in df.columns:
        # Skip columns that are already numeric
        if pd.api.types.is_numeric_dtype(df[col]):
            continue

        sample = df[col].dropna().head(100)
        cleaned = sample.astype(str).str.strip()

        # Detect currency prefix/suffix
        currency_cleaned = cleaned.str.replace(r"[$€£¥₹]", "", regex=True).str.strip()

        # US format: 1,234.50 (or plain integers like 1000)
        us_pattern = currency_cleaned.str.match(r"^-?\d{1,3}(,\d{3})*(\.\d+)?%?$")
        # EU format: 1.234,50
        eu_pattern = currency_cleaned.str.match(r"^-?\d{1,3}(\.\d{3})*(,\d+)?%?$")
        # Plain number: 1000, 123.45, -42
        plain_pattern = currency_cleaned.str.match(r"^-?\d+(\.\d+)?%?$")

        if us_pattern.mean() > 0.8:
            parsed = (
                currency_cleaned.str.replace(",", "", regex=False)
                .str.replace("%", "", regex=False)
                .pipe(pd.to_numeric, errors="coerce")
            )
            if cleaned.str.contains("%").any():
                parsed = parsed / 100
            df[col] = pd.to_numeric(
                df[col]
                .astype(str)
                .str.replace(r"[$€£¥₹,]", "", regex=True)
                .str.replace("%", "", regex=False),
                errors="coerce",
            )
            steps.append(
                TransformationStep(
                    step_type="numeric_parsed",
                    description=f"Column '{col}': parsed as US-locale number.",
                    rows_affected=int(df[col].notna().sum()),
                )
            )
        elif eu_pattern.mean() > 0.8 and not plain_pattern.mean() > 0.8:
            df[col] = pd.to_numeric(
                df[col]
                .astype(str)
                .str.replace(r"[$€£¥₹.]", "", regex=True)
                .str.replace(",", ".", regex=False)
                .str.replace("%", "", regex=False),
                errors="coerce",
            )
            steps.append(
                TransformationStep(
                    step_type="numeric_parsed",
                    description=f"Column '{col}': parsed as EU-locale number (period as thousands, comma as decimal).",
                    rows_affected=int(df[col].notna().sum()),
                )
            )
        elif plain_pattern.mean() > 0.8:
            # Plain numbers without locale formatting
            df[col] = pd.to_numeric(
                df[col]
                .astype(str)
                .str.replace(r"[$€£¥₹]", "", regex=True)
                .str.replace("%", "", regex=False),
                errors="coerce",
            )
            steps.append(
                TransformationStep(
                    step_type="numeric_parsed",
                    description=f"Column '{col}': parsed as plain number.",
                    rows_affected=int(df[col].notna().sum()),
                )
            )
    return df, steps


def _parse_date_columns(
    df: pd.DataFrame,
) -> Tuple[pd.DataFrame, List[TransformationStep]]:
    steps: List[TransformationStep] = []
    for col in df.columns:
        if pd.api.types.is_string_dtype(df[col]) or df[col].dtype == object:
            sample = df[col].dropna().head(50).astype(str)
            # Check for ambiguous dates like 01/02/2023 (could be Jan 2 or Feb 1)
            ambiguous_pattern = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
            ambiguous_hits = sample.str.match(ambiguous_pattern).mean()

            parsed = pd.to_datetime(df[col], errors="coerce")
            success_rate = parsed.notna().mean()

            if success_rate > 0.7:
                df[col] = parsed
                msg = f"Column '{col}': parsed as date."
                if ambiguous_hits > 0.5:
                    msg += " ⚠ Ambiguous MM/DD vs DD/MM format — assumed MM/DD. Verify with data owner."
                steps.append(
                    TransformationStep(
                        step_type="date_parsed",
                        description=msg,
                        rows_affected=int(parsed.notna().sum()),
                        requires_approval=ambiguous_hits > 0.5,
                    )
                )
    return df, steps


# ---------------------------------------------------------------------------
# Parquet writing
# ---------------------------------------------------------------------------


def _to_parquet(
    dataset_id: str,
    file_bytes: bytes,
    filename: str,
    df: pd.DataFrame,
) -> DatasetVersion:
    content_hash = hashlib.sha256(file_bytes).hexdigest()
    version_id = str(uuid.uuid4())

    os.makedirs(PARQUET_DIR, exist_ok=True)
    parquet_path = os.path.join(PARQUET_DIR, f"{dataset_id}_{version_id}.parquet")

    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, parquet_path)

    return DatasetVersion(
        id=version_id,
        dataset_id=dataset_id,
        version_number=1,
        parquet_path=parquet_path,
        content_hash=content_hash,
        row_count=len(df),
        column_count=len(df.columns),
        source_filename=filename,
        file_size_bytes=len(file_bytes),
    )


# ---------------------------------------------------------------------------
# Dictionary proposal
# ---------------------------------------------------------------------------


def _propose_dictionary(df: pd.DataFrame) -> List[DataDictionaryEntry]:
    entries: List[DataDictionaryEntry] = []
    for col in df.columns:
        role = _infer_column_role(df, col)
        currency = _detect_currency(df, col)
        sample = df[col].dropna().head(5).tolist()
        entries.append(
            DataDictionaryEntry(
                column=col,
                role=role,
                currency_symbol=currency,
                sample_values=sample,
            )
        )
    return entries


def _infer_column_role(df: pd.DataFrame, col: str) -> ColumnRole:
    series = df[col]

    # Date
    if pd.api.types.is_datetime64_any_dtype(series):
        return ColumnRole.date
    col_lower = col.lower()
    if any(w in col_lower for w in ("date", "time", "year", "month", "day", "period")):
        return ColumnRole.date

    # Identifier
    if any(w in col_lower for w in ("id", "uuid", "key", "code", "sku", "number")):
        nunique = series.nunique()
        if nunique > len(df) * 0.8:
            return ColumnRole.identifier

    # Measure
    if pd.api.types.is_numeric_dtype(series):
        return ColumnRole.measure
    cleaned = (
        series.dropna()
        .astype(str)
        .str.replace(r"[$€£¥₹,. %]", "", regex=True)
    )
    if cleaned.str.isnumeric().mean() > 0.8:
        return ColumnRole.measure

    # Dimension
    nunique = series.nunique()
    if nunique < min(50, len(df) * 0.5):
        return ColumnRole.dimension

    return ColumnRole.other


def _detect_currency(df: pd.DataFrame, col: str) -> Optional[str]:
    sample = df[col].dropna().astype(str).head(50)
    for symbol in ["$", "€", "£", "¥", "₹"]:
        if sample.str.contains(re.escape(symbol), regex=False).mean() > 0.3:
            return symbol
    return None


# ---------------------------------------------------------------------------
# DuckDB connection helper
# ---------------------------------------------------------------------------


def get_duckdb_connection(parquet_path: str) -> duckdb.DuckDBPyConnection:
    """Return a DuckDB in-memory connection with a 'data' view over the parquet file."""
    conn = duckdb.connect(":memory:")
    conn.execute(f"CREATE OR REPLACE VIEW data AS SELECT * FROM read_parquet('{parquet_path}')")
    return conn
