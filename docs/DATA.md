# Documented offer imports

Use UTF-8 JSONL: one JSON object per line. The interface also accepts a JSON array. Fields are validated before importing. Use real observations, not copied template values.

The table below describes the import schema implemented in this published checkout. The [expanded development catalog](CATALOG_EXPANSION.md) also includes Reliance Digital, but its adapter/schema extension has not been ported here; do not import those records into this checkout. Development Reliance identities use the first 24 hexadecimal characters of SHA-256 of the full product slug and a direct HTTPS `/product/...` URL.

Required fields:

| Field | Meaning |
|---|---|
| retailer | `Amazon` or `Flipkart` |
| source_id | Amazon ASIN or Flipkart PID matching the URL; item IDs are supported for unresolved input URLs |
| title | Exact product title |
| url | Direct HTTPS Amazon.in `/dp/ASIN` or Flipkart `/p/itm...` link |
| source_kind | `manual` or `historical` for browser imports |

Optional fields include `category`, `product_type`, `attributes`, `brand`, `model`, `ram_gb`, `storage_gb`, `cpu`, `gpu`, `vram_gb`, `color`, `weight_kg`, `gaming`, `upgradeable_ram`, `features`, `price`, `shipping`, `currency`, `availability`, `condition`, `observed_at`, `source_note` and `evidence`.

Version 0.2 supports categories listed in `shortlist/taxonomy.py`, including `clothing`, `footwear`, `furniture`, `bedding`, `appliance`, `smartphone` and `headphones`. Supply the category explicitly for reliable imports; omitted categories are inferred from the title or marked `other`. For clothing, `attributes` can contain documented `material`, `color`, `size` and `audience` values, for example `{"material":"cotton","size":"M"}`. A cotton blend is recorded as `cotton blend`, not pure cotton. A list of available sizes must not be substituted for the selected variant’s size.

- Currency is currently `INR` only.
- Availability is `in_stock`, `out_of_stock` or `unknown`.
- Condition is `new`, `used`, `refurbished` or `unknown`.
- Unknown numeric/boolean fields must be `null` or omitted. No model-generated specifications.
- `observed_at` is an ISO timestamp including timezone from the actual source check. Omit it for historical/unverified records. Future timestamps are rejected.
- `evidence` maps field names to exact supporting source text; `source_note` explains the source/check limitations.
- Price excludes conditional card, EMI and exchange offers. Add known shipping separately; leave it `null` when unknown.
- Cross-store matching requires all exact-variant fields. Do not substitute a broad model family for a verified variant identifier.
- Browser imports are limited to 500 records / 2 MB at a time.

For example, the structure of a manual record is below. **This is a schema illustration, not a real offer; replace every placeholder with observed facts.**

```json
{
  "retailer": "Amazon",
  "source_id": "REPLACE_WITH_REAL_ASIN",
  "title": "Exact observed laptop title",
  "url": "https://www.amazon.in/dp/REPLACE_WITH_REAL_ASIN",
  "price": null,
  "shipping": null,
  "currency": "INR",
  "availability": "unknown",
  "source_kind": "manual",
  "observed_at": null,
  "source_note": "Describe how and when the record was collected.",
  "evidence": {"title": "Exact observed laptop title"}
}
```

The example intentionally fails source-ID validation until replaced with an actual product. We do not seed invented products into the research catalog.
