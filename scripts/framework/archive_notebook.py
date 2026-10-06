"""Generate the reviewed Untitled notebook's non-destructive archive normalisation.

Only general exploration is templated. Thesis-specific comparison tables have
fixed treatment/control requirements and are not applied to arbitrary queues.
"""
from __future__ import annotations
import hashlib
from pathlib import Path

REFERENCE_SHA256 = '0b83ee3fe9ab0fa095eb9fe4abc3e42415a68b3d91ebb0a8136f883112af6b26'
CELLS = [('markdown',
  '# Experiment archive exploration\n'
  '\n'
  "`archive.json` beside `runs.csv` defines the export's types, null marker, metric definitions and hashes. "
  '`load_archive()` reads that schema and preserves nullable `string`, `Int64`, `Float64` and `boolean` '
  "types, including entirely empty columns. It does not use pandas' default missing-value guesses.\n"
  '\n'
  'Run all cells after selecting `data_dir`. `raw_df` preserves the typed export; `df` adds UTC timestamp '
  'conversion and diagnostic indicators. No CSV or repository files are written. Empty diagnostic strings '
  'remain empty; the archive null marker is decoded by the loader.\n'
  '\n'
  'For charts, select matching workload, payload, network condition and firmware controls. Use normalised '
  'timing columns rather than raw zero placeholders, honour `timing_policy_exclusion`, and keep failed '
  'attempts when studying reliability. `partial` and unavailable-field diagnostics do not invalidate every '
  'measurement in a row. TLS aggregate and invocation timings overlap and must not be added together. '
  '`row_id` identifies rows; `run_id` can repeat.\n'),
 ('code',
  'from pathlib import Path\n'
  'import json\n'
  'import hashlib\n'
  'import sys\n'
  'import pandas as pd\n'
  'from IPython.display import display\n'
  '\n'
  '# The notebook opens beside runs.csv. A repository-root kernel is also supported.\n'
  "candidates = [Path.cwd(), *Path.cwd().parents, Path('/workspace')]\n"
  "repo_root = next((p for p in candidates if (p / 'scripts/framework/archive_table.py').is_file()), None)\n"
  'if repo_root is None:\n'
  "    raise RuntimeError('Open this notebook in the framework Jupyter environment.')\n"
  "sys.path.insert(0, str(repo_root / 'scripts'))\n"
  'from framework.archive_table import load_archive\n'
  '\n'
  "data_dir = Path.cwd() if (Path.cwd() / 'archive.json').is_file() else repo_root / EXPORT_RELATIVE_PATH\n"
  "if hashlib.sha256((data_dir / 'queue-selection.json').read_bytes()).hexdigest() != EXPECTED_SELECTION_SHA256:\n"
  "    raise ValueError('This directory does not match the notebook export selection.')\n"
  "csv_file = data_dir / 'runs.csv'\n"
  'raw_df = load_archive(data_dir)\n'
  "archive_schema = json.loads((data_dir / 'archive.json').read_text())\n"
  "selection = json.loads((data_dir / 'queue-selection.json').read_text())\n"
  'df = raw_df.copy(deep=True)\n'
  "print(f'Loaded: {csv_file}; rows: {len(df):,}; columns: {len(df.columns)}')\n"
  "display(pd.DataFrame(selection['jobs']))\n"),
 ('code',
  'type_summary = (\n'
  '    df.dtypes\n'
  '      .astype(str)\n'
  '      .value_counts()\n'
  '      .rename_axis("dtype")\n'
  '      .reset_index(name="columns")\n'
  ')\n'
  '\n'
  'display(type_summary)\n'
  '\n'
  'for dtype in df.dtypes.astype(str).unique():\n'
  '    cols = df.columns[df.dtypes.astype(str) == dtype].tolist()\n'
  '\n'
  '    print(f"\\n{dtype}: {len(cols)} columns")\n'
  '    print(cols)\n'
  '\n'
  '    '),
 ('code',
  '# The archive loader already applies the authoritative nullable types.\n'
  '# Preserve numeric status/result codes, raw placeholders, and legitimate zero values.\n'
  '# Add only an explicit timestamp conversion; invalid timestamps should raise.\n'
  'df["created_at"] = pd.to_datetime(raw_df["created_at"], errors="raise", utc=True)\n'
  '\n'
  '# Optional local-time view without changing the stored UTC timestamps:\n'
  '# df["created_at"].dt.tz_convert("Australia/Melbourne")'),
 ('code',
  '# Expand diagnostic codes for exploration, not as a whole-row quality score.\n'
  '# Remove previously derived columns so this cell can safely be rerun.\n'
  'derived_cols = [c for c in df if c.startswith("analysis_error__") or c == "analysis_error_count"]\n'
  'df = df.drop(columns=derived_cols)\n'
  'error_sets = df["analysis_errors"].fillna("").map(\n'
  '    lambda value: {code.strip() for code in value.split(";") if code.strip()}\n'
  ')\n'
  'error_types = sorted({code for codes in error_sets for code in codes})\n'
  'error_columns = {code: "analysis_error__" + code.replace(":", "__") for code in error_types}\n'
  'if len(set(error_columns.values())) != len(error_columns):\n'
  '    raise ValueError("Diagnostic column names collide; retain the original error codes.")\n'
  '\n'
  'print(f"Found {len(error_types)} analysis error types:")\n'
  'for error, column in error_columns.items():\n'
  '    print(f"  {error}")\n'
  '    df[column] = error_sets.map(lambda codes: error in codes).astype("boolean")\n'
  'analysis_error_cols = list(error_columns.values())\n'
  'error_summary = pd.DataFrame({\n'
  '    "error": error_types,\n'
  '    "rows": [int(df[column].sum()) for column in analysis_error_cols],\n'
  '})\n'
  'display(error_summary)\n'
  'df["analysis_error_count"] = error_sets.map(len).astype("Int64")'),
 ('code',
  '# Check that normalisation has preserved all original values except timestamp representation.\n'
  'original_columns = [c for c in raw_df if c != "created_at"]\n'
  'pd.testing.assert_frame_equal(df[original_columns], raw_df[original_columns])\n'
  'assert df["row_id"].is_unique, "row_id must remain unique; run_id can legitimately repeat."\n'
  'assert df["created_at"].isna().equals(raw_df["created_at"].isna())\n'
  'assert df["created_at"].equals(pd.to_datetime(raw_df["created_at"], errors="raise", utc=True))\n'
  '\n'
  'schema_summary = pd.DataFrame({\n'
  '    "column": list(archive_schema["columns"]),\n'
  '    "schema_type": list(archive_schema["columns"].values()),\n'
  '})\n'
  'schema_summary["loaded_dtype"] = schema_summary["column"].map(raw_df.dtypes.astype(str))\n'
  'schema_summary["analysis_dtype"] = schema_summary["column"].map(df.dtypes.astype(str))\n'
  'print("Passed: original values, missingness, nullable types, row identity and timestamps preserved.")\n'
  'display(schema_summary)'),
 ('code',
  'rows = []\n'
  '\n'
  'for col in df.columns:\n'
  '    counts = df[col].value_counts(dropna=True)\n'
  '\n'
  '    row = {\n'
  '        "column": col,\n'
  '        "dtype": str(df[col].dtype),\n'
  '        "populated": df[col].notna().sum(),\n'
  '        "missing": df[col].isna().sum(),\n'
  '        "missing_pct": round(df[col].isna().mean() * 100, 1),\n'
  '        "unique": df[col].nunique(dropna=True),\n'
  '    }\n'
  '\n'
  '    for i in range(3):\n'
  '        if i < len(counts):\n'
  '            row[f"top_{i+1}"] = f"{counts.index[i]} ({counts.iloc[i]})"\n'
  '        else:\n'
  '            row[f"top_{i+1}"] = ""\n'
  '\n'
  '    rows.append(row)\n'
  '\n'
  'column_profile = pd.DataFrame(rows)\n'
  '\n'
  'with pd.option_context(\n'
  '    "display.max_rows", None,\n'
  '    "display.max_colwidth", 80\n'
  '):\n'
  '    display(column_profile)')]

def write_notebook(output: Path, repo_root: Path) -> Path:
    import nbformat
    cells = []
    for kind, source in CELLS:
        if kind == 'code':
            source = source.replace('EXPORT_RELATIVE_PATH', repr(output.relative_to(repo_root).as_posix()))
            source = source.replace('EXPECTED_SELECTION_SHA256', repr(hashlib.sha256((output / 'queue-selection.json').read_bytes()).hexdigest()))
        cells.append(nbformat.v4.new_code_cell(source) if kind == 'code'
                     else nbformat.v4.new_markdown_cell(source))
    cells.append(nbformat.v4.new_markdown_cell(
        "## Your analysis\n\n`raw_df` retains every exported attempt; `df` adds timestamps and diagnostics. "
        "Filter matching campaigns, source identities, payloads and network conditions before comparing. "
        "Accepted failures remain failures. Retries retain earlier attempts: define your selection rule "
        "before summarising. Normalised timing fields come from the archive exporter; missing values "
        "remain missing. TLS aggregate and invocation timings overlap. "
        "Use `row_id` for row identity and retain evidence/validity columns with any derived tables."))
    cells.append(nbformat.v4.new_code_cell(
        "# Begin your analysis here. This view retains failures for reliability inspection.\n"
        "display(df.groupby(['campaign_id', 'execution_outcome'], dropna=False).size().rename('rows'))"))
    book = nbformat.v4.new_notebook(cells=cells, metadata={
        'kernelspec': {'name': 'python3', 'display_name': 'Python 3', 'language': 'python'},
        'pqc_normalisation_reference_sha256': REFERENCE_SHA256,
    })
    path = output / 'analysis.ipynb'
    nbformat.write(book, path)
    return path
