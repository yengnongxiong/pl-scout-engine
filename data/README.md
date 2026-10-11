# Data folder

Data is created on your machine and never committed, except the hand-made corrections in
`overrides/`.

| Folder | What it holds | Committed? |
|---|---|---|
| `raw/` | Untouched copies of everything downloaded, one timestamped folder per fetch, so any build can be replayed offline. | No (personal use only) |
| `warehouse/` | The SQLite database the dashboard reads, plus build and training summaries. | No |
| `models/` | Trained models with metadata (training data window, features, metrics, git commit). | No |
| [`overrides/`](overrides/) | Manual corrections, each with a reason and a date: player links between sources (`player_overrides.csv`) and market values (`market_value_overrides.csv`). | Yes |

`uv run scout demo` (or `scout ingest`, `scout build`, `scout train`) fills these in.
