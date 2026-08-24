# Data Directory

This directory is where the ParcelPilot assessment data pack must be placed **locally**. It is intentionally **not included** in this repository — see `docs/git-development-plan.md` §2 ("Data-handling policy") for the full rationale.

## Expected layout

```
data/
├── ParcelPilot_Assessment_Data.xlsx
└── documents/
    ├── 01_Support_Policy_v3_CURRENT.pdf
    ├── 02_Support_Policy_v2_DEPRECATED.pdf
    ├── 03_Cancellation_and_Service_Credit_SOP_v4.pdf
    ├── 04_Product_Operations_Guide_and_Known_Issues.pdf
    ├── 05_Northstar_Logistics_Enterprise_Agreement.pdf
    └── 06_LumenWorks_Service_Agreement.pdf
```

These are exactly the filenames named in CalQuity's own assessment brief's "Candidate Data Pack" section — nothing here is a secret in itself; what's excluded is the *content* of the files and any verbatim transcription of it.

## Obtaining the data

If you were issued this assessment, place the files you were given in the layout above. The ingestion pipeline added in a later milestone (`backend/ingestion/`, see `docs/git-development-plan.md` Milestone 0) reads only from this directory. It is designed to be schema/shape-driven rather than hard-coded to these specific filenames or record IDs, so it should also work against a substituted or extended version of the same pack (per the assessment brief's own note that other records/questions from the same source pack may be used for evaluation).

## Why the data isn't committed

The workbook and documents are CalQuity's proprietary hiring-assessment materials, and this repository is required to be public. Committing them — or a full-detail transcription of their content — would expose material that the assessment brief treats as evaluative (e.g., exact policy numbers, contract terms, and which historical answers are wrong and why). The automated test suite does not depend on this directory at all: it runs entirely against small, synthetic fixtures with fictional companies and numbers that mirror the *shape* of the real pack (see `tests/fixtures/`, added in the ingestion milestone), which also happens to be direct proof that the system generalizes rather than being hard-coded to the specific example records in the brief.
