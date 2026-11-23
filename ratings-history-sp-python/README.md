# S&P local ZIP parser

Standalone Python 3.9+ parser for already-downloaded S&P SEC rating-history ZIPs.
Run these commands from the repository root:

```sh
python ratings-history-sp-python/parse_sp.py "SP-Corporate-2026-11-01.zip" --output-dir sp-output
```

CSV uses only the Python standard library. To write Parquet too:

```sh
python -m pip install -r ratings-history-sp-python/requirements.txt
python ratings-history-sp-python/parse_sp.py "SP-Corporate-2026-11-01.zip" --output-dir sp-output --format both
```

`--format parquet` writes only Parquet. Default is CSV. `--batch-size 25000`
controls the Parquet buffer. Existing outputs are refused unless `--overwrite`
is supplied. The source archive is read directly, never extracted or modified.
Output names follow `YYYYMMDD agency category.csv` / `.parquet`, using the
XML disclosure date, agency name, and SEC category. `parse_summary.json` records
file and rating-record counts. No changes to the existing Node/React apps are
needed, and the standalone parser is not automatically wired into the website.

## Exact parsing contract

The 32 columns and their order match the existing TypeScript parser. An `ORD`
produces one obligor-rating row; an `INRD` produces one instrument-rating row.
Only explicit XML ancestor metadata is inherited: `ROCRA` -> `OD` -> `ORD`, or
`ROCRA` -> `ISD` -> `IND` -> `INRD`. No field is inherited from a previous sibling
record, instrument, or entity. Entity-level ratings remain in obligor columns;
no issuer/obligor coalescing is performed. No identifiers are inferred from filenames.

All values remain strings: no date conversion, numeric conversion, stripping,
rating mapping, filtering, deduplication, sorting, aggregation, financial joins,
or forward-filling. Repeated source records and original archive/XML record order
are preserved. XML entity decoding and XML-standard line-ending normalization
are intrinsic to XML parsing. Missing elements are `None`; present empty elements
are empty strings. Parquet preserves that distinction; ordinary CSV writes both
as empty fields, as the existing repository does. XML context/schema declarations
are structural metadata, not extra CSV fields. The source ZIP remains the lossless
record of XML markup, attributes and presence information.

The parser uses namespace-aware ElementTree parsing, releasing completed elements,
and bounded Parquet batches. Unknown ratings-namespace fields, repeated scalar
fields and malformed XML fail explicitly rather than silently dropping data.
Temporary outputs are removed on parsing failure; existing published files are
untouched until the complete archive has been parsed. Publication is atomic per
file, not transactional across the entire collection. Do not run concurrent
conversions into the same output directory.

## Supplied archive

`SP-Corporate-2026-11-01.zip` contains 23,733 XML documents: 10,324 OBLIGOR files
and 13,409 ISSUER files, containing 116,898 instrument sections. There are
248,842 obligor-rating records and 918,394 instrument-rating records, totaling
1,167,236 rows. Files are not simply one unique company each: obligor and issuer
histories are separate, and multiple instrument sections can describe the same
issuance under different supplied identifier schemes. Everything is retained.

The complete dataset exceeds Excel's 1,048,576 worksheet rows. Neither CSV nor
Parquet has that worksheet restriction. Parquet is compressed and supports batch
reading, but loading it into an Excel worksheet still faces Excel's grid limit.
Use Python/batched queries, or load an appropriate source through Excel's Data
Model and inspect subsets separately. Do not overwrite the full CSV by saving
an incomplete worksheet view.

## Tests

```sh
python -m unittest discover -s ratings-history-sp-python -v
```
