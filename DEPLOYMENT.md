# Deployment readiness

This project exposes a reusable clarification-aware Text-to-SQL pipeline in
`telecom_text_to_sql/pipeline.py`. The terminal application in
`text_to_sql.py` is a thin client
of that pipeline, so an API or worker can call the same tested implementation
without triggering interactive input during import.

## Prerequisites

1. Install Python dependencies:

   ```powershell
   py -3 -m pip install -r requirements.txt
   ```

2. Install and start Ollama, then make both local models available:

   ```powershell
   ollama pull llama3.2
   ollama pull nomic-embed-text
   ```

3. Copy `.env.example` to `.env` and enter the PostgreSQL connection values.

4. Import the telecom dataset when initializing a new database:

   ```powershell
   py -3 scripts\import_data.py
   ```

## Run the user interface

Start the local browser interface from the project root:

```powershell
py -3 -m streamlit run streamlit_app.py --server.address localhost
```

The interface supports normal questions, multi-turn clarification, generated
SQL inspection, complete-result CSV downloads, and display-only row limits.
Closing the terminal or pressing `Ctrl+C` stops the local server.

## Required checks

Run deterministic unit and regression tests:

```powershell
py -3 -m unittest discover -s tests -v
```

Run the original clarification benchmark:

```powershell
py -3 evaluation\evaluate_clarification.py
```

Run the deployment gate with three independent passes:

```powershell
py -3 evaluation\evaluate_end_to_end.py --runs 3
```

The end-to-end command exits with code `0` only when every configured release
gate passes. It measures:

- clear-versus-ambiguous classification;
- clarification precision, recall, and F1;
- multi-turn clarification completion;
- generated SQL validation;
- result equivalence against reference SQL executed on PostgreSQL;
- unsafe-query rejection and safe-query acceptance;
- runtime failures;
- mean and p95 latency;
- output stability across repeated model runs.

The detailed JSON report is written to `evaluation/reports/latest.json`. The
report directory is ignored by Git because reports are environment-specific.

Use `--no-execute` only for diagnostics. A run without database result
comparison cannot pass the deployment gate.

## Programmatic use

```python
from telecom_text_to_sql import run_pipeline

result = run_pipeline(
    "Which customers have monthly charges above 100?",
    execute=True,
)

if result.status == "success":
    print(result.sql)
    print(result.columns)
    print(result.rows)
elif result.status == "needs_clarification":
    print(result.clarification_questions[-1])
else:
    print(result.error or result.sql_validation_errors)
```

Possible statuses are `success`, `needs_clarification`, `unsupported`,
`sql_rejected`, and `error`. Predictive, data-changing, administrative, and
credential requests return `unsupported` before model or database access.

The verified language and schema boundary is documented in
`SUPPORTED_QUESTIONS.md`. A question outside that contract must be added to the
scenario matrix with an expected result before support is claimed.

## Production boundary

Passing this repository's release gate establishes readiness for the 83-case
supported telecom scenario matrix and its language categories. It does not
claim correctness for every possible sentence or database question. A public deployment still needs an API
or UI layer with authentication, request-size limits, rate limiting, request
timeouts, structured logging, health checks, secret management, and monitoring.
The database account should also have PostgreSQL-level read-only permissions;
application validation and read-only transactions are additional safeguards,
not substitutes for least-privilege credentials.
