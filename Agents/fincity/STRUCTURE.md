# FinCity Graph Engine

- `main.py` serves the static graph UI and graph, time-window, account case-file,
  cluster-transaction, and Courtroom APIs.
- `data_loader.py` builds snapshots from at most `FINCITY_MAX_TRANSACTIONS` rows
  (default: 100,000). It reads the local CSV for development, or samples a
  configured BigQuery table when `FINCITY_BIGQUERY_TABLE` is set. Each requested
  time window is aggregated and reduced to the most active accounts.
- `graph_queries.py` contains parameterized BigQuery SQL templates for adjacency,
  account metrics, ring metrics, temporal evolution, and case files. The SQL
  assumes an enriched transaction table with an `isFraud` label and precomputed
  component tables; configure those table identifiers for the target project.
- `static/index.html`, `static/graph.js`, `static/controls.js`, and
  `static/style.css` implement the responsive animated canvas graph, filters,
  play/scrub timeline, account case files, cluster selection, and Courtroom trial
  view.

The checked-in transaction CSV does not have an `isFraud` label. In that local
demo, FinCity identifies review candidates with a transparent transaction
heuristic (TRANSFER/CASH_OUT, top 5% amount, and at least 90% sender-balance
depletion) and labels them as such; it does not claim that those transactions
are confirmed fraud. If a labeled dataset is supplied, its observed labels are
used instead. Unlabeled candidates are sent to the Courtroom without inventing
a scorer probability.

## Run and deploy

Run locally from the repository root with `uvicorn Agents.fincity.main:app
--reload`. The local CSV is capped at 100,000 rows by default; set
`FINCITY_MAX_TRANSACTIONS` to change the limit.

Build the standalone image from the repository root with
`docker build -f Agents/fincity/Dockerfile -t fincity .`. Deploy that image to
Cloud Run with `FINCITY_BIGQUERY_TABLE` set to a fully-qualified
`project.dataset.table` and a service account allowed to create BigQuery jobs
and read that table. The BigQuery source samples up to the configured row cap;
the frontend renders at most 2,000 accounts. The Courtroom trial endpoint also
needs the Courtroom agent dependencies and Gemini credentials in the runtime.
