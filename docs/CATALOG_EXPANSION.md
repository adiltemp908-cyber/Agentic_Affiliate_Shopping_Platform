# Catalog expansion through 3 November 2026

The populated development catalog grew from **26,715 to 57,361 retailer listings**, a net increase of **30,646** since 31 October. It now represents Amazon India, Flipkart and Reliance Digital across 23 category groups, including Other.

This is a dated development record. The public source checkout still contains the Amazon/Flipkart implementation and `broad`/`extended` profiles. The newer retailer adapter and collection profiles described below have not been ported into this source tree. The catalog database, raw pages and full development reports remain excluded from Git. Available commands are documented in [Setup](SETUP.md).

## Expansion history

Dates below use India Standard Time. Additions count new retailer listing records after deduplication; refreshing an existing observation does not count as a new listing.

| Completed | Collection stage | Net new listings | Total after stage |
|---|---|---:|---:|
| 31 October | Baseline | — | 26,715 |
| 1 November | `more`: accessories, home, fashion and other departments | 7,864 | 34,579 |
| 2 November | Amazon-focused discovery and refresh | 63 | 34,642 |
| 2 November | `additional`: 75 Flipkart departments checked, 69 with imports | 7,856 | 42,498 |
| 3 November | Reliance Digital: 13 categories | 960 | 43,458 |
| 3 November | `further`: 89 previously unused Flipkart departments | 13,903 | 57,361 |

The `more` plan covers 85 departments. The Amazon-focused run added 35 listings with observed prices and 28 with unknown prices; existing-record refreshes brought its recent priced count to 132 at the end of that run. HTTP 503 responses and product pages withholding prices limited collection. Unknown prices were retained as unknown.

Reliance Digital added 960 priced listings; 263 were marked unavailable. Its development collector matches collection cards to the same product in embedded page state and requires an explicit INR selling price with matching minimum and maximum. It excludes MRP and conditional discounts. Only the first collection page is fetched because query pagination is excluded by the retailer crawl policy. Product identity is derived from the full product permalink slug, preserving variant distinctions.

The final Flipkart sweep broadened books, sports, decor, accessories, bags, personal care, kitchenware, bedding, toys, appliances, clothing, furniture and groceries. All 13,903 new records had observed prices. This does not establish checkout availability or delivery.

## Latest measured coverage

Snapshot: **3 November 2026, 10:25 IST** (`2026-11-03T04:55:58.642295+00:00`). The [machine-readable summary](catalog-snapshot-2026-11-03.json) preserves aggregate counts, reported validation results and SHA-256 fingerprints of its two local source reports.

| Retailer | Total | Recent observations | Recent priced, not marked unavailable | Recent unavailable |
|---|---:|---:|---:|---:|
| Amazon India | 12,572 | 0 | 0 | 0 |
| Flipkart | 43,829 | 22,144 | 22,144 | 0 |
| Reliance Digital | 960 | 960 | 697 | 263 |
| **Total** | **57,361** | **23,104** | **22,841** | **263** |

Recent means observed in the preceding 24 hours at the snapshot time. Amazon's observations had expired by then; this is a freshness gap, not a finding about retailer inventory. The catalog also contained 22,021 stale and 12,236 explicitly historical records, with no unverified or fixture records. Earlier recent counts cannot be added together because observations expire between runs.

### Category coverage

Recent counts below include unavailable listings; they are not the number of usable recommendations. Categories are application groups, not a complete product ontology.

| Category | Total listings | Recent observations |
|---|---:|---:|
| `accessory` | 4,280 | 1,878 |
| `appliance` | 3,212 | 679 |
| `bag` | 2,296 | 902 |
| `beauty` | 2,681 | 978 |
| `bedding` | 4,288 | 1,893 |
| `book` | 4,466 | 3,494 |
| `camera` | 906 | 64 |
| `clothing` | 5,141 | 1,539 |
| `cookware` | 5,270 | 2,755 |
| `decor` | 4,634 | 2,376 |
| `footwear` | 1,245 | 0 |
| `furniture` | 3,582 | 1,173 |
| `grocery` | 2,738 | 1,556 |
| `headphones` | 922 | 81 |
| `laptop` | 930 | 95 |
| `monitor` | 745 | 25 |
| `other` | 85 | 6 |
| `smartphone` | 847 | 100 |
| `smartwatch` | 224 | 75 |
| `sports` | 4,250 | 1,745 |
| `tablet` | 878 | 119 |
| `television` | 538 | 40 |
| `toy` | 3,203 | 1,531 |

## Collection and interpretation

Collection is on demand and bounded by source policy, request pacing and failure limits. Reports allow unfinished plans to resume; a new refresh cycle needs a new report filename. Rebuild the semantic index after collection or metadata changes. See [Setup](SETUP.md) for the published collector and [Architecture](ARCHITECTURE.md) for the filtering and ranking model.

Category observations establish the displayed selling price and exact product link. They do not establish selected variants, stock, shipping, postcode delivery or final checkout cost. Product-page checks provide stronger evidence, while unknown mandatory attributes still fail hard filters. Metadata repairs preserve price observation timestamps. Historical records stay excluded from normal search.

Counts include retailer-specific listings and variants, not guaranteed distinct physical products. Coverage remains uneven: footwear had 1,245 stored records but no recent observations at this snapshot. A larger catalog does not by itself establish recommendation quality.

## Evidence and validation

The final audit recorded zero validation issues, unchanged totals for the other retailers during the final Flipkart sweep, and an index matching the catalog. The saved development validation reports 293 passing regression tests and 14 hybrid search checks. These were recorded on 3 November, not rerun as part of this documentation update. See [Validation](VALIDATION.md) for scope and limitations.

The expansion history was transcribed from these local development reports, which are not bundled in the repository:

- `more-catalog-final-validation-2026-11-01.json`
- `amazon-priority-final-validation-2026-11-02.json`
- `additional-catalog-final-validation-2026-11-02.json`
- `reliance-catalog-final-validation-2026-11-03.json`
- `further-flipkart-final-validation-2026-11-03.json`
- `further-flipkart-audit-2026-11-03.json`

The committed aggregate summary allows the documented totals to be checked without distributing product records, runtime data or raw retailer pages. Source-report fingerprints identify the inputs; they are not independent verification of retailer claims.
