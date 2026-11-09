# Sources

Historical archive: conversation transcripts, past artifacts, ingested documents.

## Structure

```
wiki_sources/
├── index.md              → Router
├── raw/                  → Immutable source packets
│   └── SRC-YYYYMMDDNN/   → One packet per source
│       ├── manifest.json
│       ├── original/     → Original file
│       └── extracted.md  → LLM-extracted text
└── by-agent/             → Conversation transcripts per agent
    └── orchestrator/
```

## Ingestion

1. Drop source into `wiki_sources/raw/` or call `wiki_capture_source` (if available).
2. LLM extracts key information and writes `extracted.md`.
3. Agent creates/updates wiki pages in `wiki_domain/` referencing the source.
4. `wiki_cascade.py` identifies pages that need refreshing.

## References

- [wiki_cascade.py](/wiki/scripts/wiki_cascade.py) — Cascading update after ingest
- [wiki_index.py](/wiki/scripts/wiki_index.py) — Index builder (registry + index.md)
