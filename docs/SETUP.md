# Local setup

## Requirements

- Python 3.11 or newer; development validation used Python 3.13 on Windows.
- A local copy of Qwen3-4B-Instruct-2507 in GGUF Q4_K_M format.
- A compatible llama.cpp server build with Vulkan support and an NVIDIA Vulkan device. The current launcher explicitly selects this device; CPU-only and other GPU backends are not implemented in the model launcher.
- A local Sentence Transformers MiniLM embedding directory producing 384-dimensional vectors.
- Internet access for source collection. Local inference itself does not call a hosted LLM provider.

Weights and executables are not downloaded automatically. Obtain them from their publishers and keep their applicable licenses with your local copies. The repository does not redistribute model assets.

## 1. Install the application

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Use an editable installation and run from this checkout; the frontend assets live in `web/` beside the Python package.

## 2. Configure model assets

```powershell
Copy-Item config/model.example.json models/model.json
notepad models/model.json
```

Set `runtime_path` to your `llama-server.exe` and `model_path` to your GGUF file. They must be real local paths. The example values are placeholders.

Put the embedding model files in `models/embedding/`, or set an override:

```powershell
$env:SHORTLIST_MODEL_MANIFEST='C:/your/models/model.json'
$env:SHORTLIST_EMBEDDINGS='C:/your/models/embedding'
```

Other overrides are `SHORTLIST_DATA`, `SHORTLIST_PORT` and `SHORTLIST_MODEL_PORT`. Defaults are the checkout's `data/`, application port `8777`, and model port `8778`. Windows shortcut scripts assume application port 8777. Local tracing is disabled. The app generates its own localhost model key in ignored runtime storage.

## 3. Populate an empty catalog

A fresh checkout contains no commercial catalog or saved conversations. Start with a small public category or a known product link:

```powershell
python -m shortlist collect 'https://www.flipkart.com/televisions/oled~screen-type/pr?sid=ckf%2Cczl' --pages 3 --category television
python -m shortlist discover 'https://www.amazon.in/s?k=round+digital+alarm+clock' --limit 8
python -m shortlist refresh 'https://www.amazon.in/dp/YOUR_ASIN'
```

Replace `YOUR_ASIN` with an actual product ID. Source access is not guaranteed. A failed check is not evidence of stock or a fresh price. Alternatively, import documented observations using the [data contract](DATA.md):

```powershell
python -m shortlist import path/to/observations.jsonl
```

For broader, resumable collection:

```powershell
python scripts/collect_catalog.py --profile broad --report reports/broad-run.json
python scripts/collect_catalog.py --profile extended --report reports/extended-run.json
```

`config/catalog_sources.json` contains public seed URLs. The broad profile covers 54 groups; the extended profile adds 29. Request counts are bounded, each retailer has a paced worker, and repeated unsuccessful groups stop that retailer. Rerunning the same report resumes unfinished jobs. Use a new report for a new refresh cycle. This is user-triggered collection, not an automatic daily feed.

For an existing Amazon catalog when search discovery is unavailable:

```powershell
python scripts/refresh_known_amazon.py --limit 30
python scripts/expand_amazon_related.py --limit 40
```

These tools need previously collected records. They check known URLs or links discovered from accessible product pages. Every imported price is read from its own product page. Neither tool bypasses source policy, and unavailable or ambiguous pages remain recorded failures/unknowns.

## 4. Index and launch

```powershell
python -m shortlist index
python -m shortlist serve
```

Open **http://127.0.0.1:8777**. The first conversational query loads the local model. Rebuild the index after adding listings or changing descriptions. Unchanged descriptions reuse cached embeddings; a stale or unavailable semantic index produces a visible keyword-search fallback.

For lexical-only exploration, disable local Qwen in Search settings and select BM25. Conversation quality is more limited in this mode, but model assets are not required for keyword retrieval.

## 5. Test or recapture examples

```powershell
python -m pytest -q
```

The unit suite uses isolated test catalogs and mocked model behavior. It does not require retailer access or model downloads.

To recapture the [showcase](SHOWCASE.md), start a populated app with local models, install Node.js and Chrome, and make Playwright available:

```powershell
npm install --no-save --package-lock=false playwright
node scripts/capture_showcase.cjs
```

The capture script requires current matching data, validates the displayed constraints, saves PNGs in `docs/screenshots/`, and writes its diagnostic summary to ignored `reports/`. A changed catalog may yield different counts or no matches; it does not manufacture screenshot results.

## Troubleshooting

| Symptom | Check |
|---|---|
| No results in a fresh checkout | Collect or import observations; the development catalog is not bundled. |
| No results after a day | The default freshness window is 24 hours. Refresh source observations. |
| No matches for a mandatory specification | Its field may be missing, or the current inventory may not satisfy it. Unknown fields cannot pass a hard filter. |
| Local model fails to start | Check manifest paths, runtime compatibility, Vulkan device detection, port 8778 and `data/model-runtime.log`. |
| Semantic search falls back to BM25 | Check embedding assets and rebuild the index. |
| Retailer returns HTTP 503 | That endpoint is unavailable to the request. Retry later; known product pages may behave differently from search pages. |

Catalogs, keys, chats, logs and model files are ignored by Git. Screenshots and source configuration are the only selected generated/reference assets committed here.
