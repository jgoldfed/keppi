---
type: concept
subtype: idea
status: active
updated: 2026-04-28
tags: [wiki, concept, data-engineering, snowflake]
related_to:
  - "[[Snowflake]]"
  - "[[Databricks]]"
  - "[[Meridian Partners]]"
---
# Medallion Architecture

A layered data architecture pattern for organizing data in a lakehouse.

## Layers

- **Bronze** (raw): Ingested exactly as-is from source systems like [[Fidelity]] and [[Schwab]].
- **Silver** (cleaned): Deduplicated, validated, conformed. See [[Data Quality]].
- **Gold** (aggregated): Business-ready aggregates served to consumers.

Uses [[Snowflake Streams and Tasks]] for change data capture.
#data-engineering #architecture
