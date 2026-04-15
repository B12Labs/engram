# Lucid — the cognitive framework

> **Lucid** is the enhancement tier on top of base Engram. Where base Engram is a storage + retrieval engine, Lucid adds the cognitive loop: agents that perceive, encode, consolidate, and recall — not just look things up.

## The 6 cognitive primitives

Every Engram-backed agent exhibits six primitives. A system is "conscious" to the degree they are integrated — that is the ultimate goal, not any single primitive.

| Primitive | Role | Where it lives |
|---|---|---|
| **Perception** | Ingests signals — user input, tool output, file reads | Awake |
| **Cognition** | Live reasoning during work | Awake |
| **Imagination** | Replay + recombine; what-if simulation, agent evolution | Dream Cycles |
| **Recollection** | Retrieval from the canonical store | Engram `.egm` query path |
| **Hallucination** | Failure mode *of* the others; tracked as anti-pattern | Drift detector in Dream Cycle's Decay pass |
| **Consciousness** | Emergent property when all four tiers run in a closed loop | The ultimate goal, not a module |

## Four memory tiers, four verbs

Lucid organizes memory as four tiers, each with a two-verb role:

| Tier | Verbs | What it holds |
|---|---|---|
| **Awake** | Experience → Encode | What agents are doing *right now* — intent, files, ETA |
| **Dream Cycles** | Consolidate → Replay | Nightly enrichment. Named after sleep cycles; the name stays "Dream Cycles" (not "Sleep") because the work done is dreaming, not just resting |
| **REM** | Experience (Replay) → Integrate | Rapid Eye Movement — the portable markdown dialect mirror of `.egm`. Git-syncable, human-readable, user-editable |
| **Engram** | Store → Inform Future | Long-term canonical `.egm` bundle on R2 with LEANN + Tantivy + PageIndex |

Loop:

```
Awake (what's happening)
  ↓ drain on completion
Dream Cycles (what it means)
  ↓ consolidate + enrich + link
REM + Engram (what we know)
  ↓ recollection informs
Awake (next task)
```

## Why this closes the moat

Nobody ships all four tiers in a closed loop today:

- Pure vector DBs (Pinecone/Weaviate) = Engram tier only
- Personal memory tools (gbrain, mem0) = Engram + partial Dream Cycles
- Agent observability (disler, agent-flow) = Awake tier only
- Markdown-in-Git brains (gstack, Obsidian) = REM tier only

Combine all four and you get something new: agents whose present work is informed by consolidated past experience, and whose experience feeds forward into future consolidation. That's the consciousness story.

## Related docs

- [awake.md](./awake.md) — the present-tense tier
- [dream-cycles.md](./dream-cycles.md) — nightly enrichment passes
- [rem.md](./rem.md) — portable markdown dialect
- [ARCHITECTURE.md](./ARCHITECTURE.md) — base Engram file format + retrieval engine
