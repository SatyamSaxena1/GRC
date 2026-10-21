# NIST Cybersecurity Framework (CSF) 2.0

| Field | Value |
|---|---|
| `csf-2.0.json` | CPRT export of the CSF 2.0 Core: functions, categories, subcategories, implementation examples |
| `NIST.CSWP.29.pdf` | The published framework document (32 pages), kept as the citation |
| JSON retrieved from | https://csrc.nist.gov/projects/cybersecurity-framework/filters#/csf/filters, using **Export → JSON** with no filters applied |
| PDF retrieved from | https://nvlpubs.nist.gov/nistpubs/CSWP/NIST.CSWP.29.pdf (DOI https://doi.org/10.6028/NIST.CSWP.29) |
| Retrieved | 2026-10-21 |
| sha256 (`csf-2.0.json`) | `05d501102c04929022b480f02cb71bae743a369d49987ef4263eb57f2ed91a2a` |
| sha256 (`NIST.CSWP.29.pdf`) | `3c31f46fee98cac0c4323453e5109291a213b4de7fef8c058af9bf67f717433c` |
| Licence | US Government work, not subject to copyright in the United States (17 U.S.C. §105). |
| May quote text in packs | Yes |

What the export contains:
- `elements`: 6 functions, 45 categories, 308 subcategory entries, 363 implementation
  examples and 91 `withdraw_reason` entries.
- The 308 subcategory entries cover only 185 unique IDs, so the list repeats IDs.
- Each `withdraw_reason` (`WR-ID.AM-06`: "Incorporated into GV.RR-02, GV.SC-02") marks a CSF
  1.1 subcategory that was withdrawn.
- `relationships`: 932 parent→child links.

A parser must de-duplicate IDs and skip withdrawn subcategories, and must check the result
against the published PDF's count before trusting it. The JSON is the parsing source; it is already
split into elements by ID (e.g. `GV.OC-01`), so it needs no PDF parsing.

**Not parsed yet.** Needs a small CPRT-JSON parser before it can be registered in
`tools/ingest_source.py::FRAMEWORKS`.
