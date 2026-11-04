# Dated validation record

## Expanded development workspace — 3 November 2026

The saved final validation at 10:25 IST records the following results. These apply to the expanded local workspace; the newer Reliance Digital adapter and collection profiles have not been ported into the published source checkout.

| Check | Recorded result |
|---|---|
| Regression tests | 293 passed |
| Hybrid search checks for the final Flipkart expansion | 14 passed |
| Catalog audit validation issues | 0 |
| Search index matches catalog | Yes |
| Local app health | Ready |
| Net new Flipkart listings | 13,903 |
| Other retailers unchanged during final sweep | Yes |

The [catalog expansion record](CATALOG_EXPANSION.md) explains the 57,361-listing snapshot and freshness limits. The [aggregate JSON](catalog-snapshot-2026-11-03.json) contains the reported results and fingerprints of the source reports. These historical tests were not rerun for this documentation change. The search checks exercise selected development cases and do not constitute a held-out relevance or shopping-suitability benchmark.

## Published source baseline — 31 October 2026

The original published baseline recorded 162 passing regression tests. Its browser captures demonstrate selected local-Qwen and hybrid-search conversations, budget/specification filtering and retained state. The [showcase](SHOWCASE.md) retains its original 31 October date; its screenshots do not depict the November catalog.

To test this checkout:

```powershell
python -m pytest -q
```

Unit tests use isolated catalogs and mocked model behavior. Live browser checks additionally need configured local models, a recent populated catalog and accessible retailer pages; follow [Setup](SETUP.md).

## Remaining limits

Neither the catalog audit nor these examples establish continuously fresh inventory, source-change resilience, independently verified product specifications, delivery guarantees, broad cross-retailer identity matching or general recommendation quality. The application remains a local single-user research system.
