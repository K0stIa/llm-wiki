# Wiki Rules

Framework protocols, pipeline rules, skill enforcement. Loaded before writing and before committing.

## Rules

- **One concept = one page.** `wiki_domain/concept-slug.md`
- **Every claim links to source.** No unattributed facts.
- **Cascading update.** Ingesting one source refreshes 10-15 existing pages.
- **Contradictions documented.** When sources disagree, both sides recorded.
- **No vector search.** Keywords only (BM25-style). No embedding service needed.
- **Two-stage recall.** Small vault (<50 pages): inline. Large vault: links-first.
- **Capability tokens file-based.** Not env vars (they die between Bash calls).

## Rules for writing pages

1. Start with the concept's name as the H1.
2. Write the concrete mechanism in the first paragraph (no metaphors).
3. Add `[link](/folder/page.md)` cross-references (minimum 2).
4. Add frontmatter: `type`, `created`, `updated`, `sources`.

## Rules for querying

1. Call `wiki_recall(query="terms")` at task start.
2. If result >50 pages: scan links, expand only chosen pages.
3. If result ≤50 pages: read inline previews.
