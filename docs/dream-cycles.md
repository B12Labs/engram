# Dream Cycles — nightly enrichment

> Nightly (or per-user rolling) cron that mirrors biological sleep cycles: each cycle runs four passes, every pass runs to completion before the next. A single user's cycle takes 20–90 seconds depending on memory volume.

The name stays **Dream Cycles** throughout the project — "Sleep" is not used as a tier name, because the work done is active (consolidating, enriching, integrating), not passive.

## Four passes per cycle

### 1. Consolidate
Merge same-entity writes from the last 24h into a single canonical entry. Dedup by SHA-256 of content. Weight by recency.

Inputs: `memory/awake/` drained on clean exit; cross-app `.egm` writes since last cycle.
Output: deduplicated canonical entries in the Engram bundle.

### 2. Enrich
Council summarization pass on long-form entries (meetings, docs, chat threads) → abstracts + tags + entity links.

Inputs: consolidated entries flagged `needs_enrich=true`.
Output: abstract (≤ 150 words), tag list, entity pointers.

### 3. Link
Entity-resolve across apps. A name in `meet.egm` + `social.egm` + `notes.egm` becomes one canonical entity pointer in `unified.egm`.

Inputs: entity mentions across all app-scoped bundles.
Output: unified entity graph. Edges carry source + confidence.

### 4. Decay
Low-signal entries (single-access, no links, low cosine similarity to anything else) archived to cold tier after 90d.

This is also where the **hallucination detector** runs: entries that drift from their sources over time (user-edited without provenance trail, or Enrich output that contradicts earlier consolidations) get flagged.

Inputs: all entries with `last_accessed > 90d ago`.
Output: archived copies in cold tier; hot tier index pruned.

## Idempotency

Re-running the same cycle produces the same output. Every pass reads current state + new inputs since last cycle, produces deterministic output. Users can trigger a manual Dream Cycle from the memory settings UI without risk.

## Cadence

- Default: 1am UTC per user (Vercel Cron)
- Heavy users: rolling window every 6h
- Manual trigger: `engram cycle --user <id>` or UI button

## Why at night?

Cost + latency. Dream Cycles are LLM-heavy (Enrich pass). Scheduling them at low-traffic hours lets us use Anthropic Batch API — 50% discount on non-interactive work. An Engram deployment that does interactive Enrich during the day pays double.

## Related

- [awake.md](./awake.md) — the tier Dream Cycles drain from
- [rem.md](./rem.md) — the markdown mirror Dream Cycles maintain
- [lucid.md](./lucid.md) — overall cognitive framework
