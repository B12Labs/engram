# Awake — the present-tense memory tier

> **Awake** is the tier that answers the question: "what are my agents doing right now?"
>
> Without it, when your IDE crashes or a session ends, you have no idea which agents were active, what files they were touching, or when they expected to finish.

## Problem Awake solves

Spawn 3 background agents to work on a feature. IDE crashes. On restart:

- No live handles to the prior agents (they died with the process)
- No filesystem breadcrumbs (agents didn't leave any)
- Git shows uncommitted work but not who was doing what or whether it's finished
- Result: you either wait blindly, risk collisions, or kill-and-restart

Engram's lower tiers answer *what happened*. Awake answers *what is happening*.

## Filesystem convention

One file per live agent, under `memory/awake/<agent-id>.md`:

```markdown
---
agent_id: a1b2c3d4
task: "short-link + activation code for /pitch"
intent: "Add /p/[slug] redirect, /api/pitch/verify OTP flow"
files:
  - app/p/[code]/page.tsx
  - app/api/pitch/verify/route.ts
  - lib/pitch/tokens.ts
started_at: 2026-04-15T04:12:03Z
heartbeat_at: 2026-04-15T04:13:45Z
eta: 2026-04-15T04:30:00Z
parent_session: 4e0f1e31-731c-48fb-be1f-da24cb9694b8
pid: 28114
worktree: main
---

Extended notes: working through the Supabase RLS policy for recipient access before wiring the verify endpoint...
```

## Lifecycle

1. **Write on spawn** — every agent, on start, writes its Awake record. Auto-wired via a `PreToolUse` hook on the Agent tool.
2. **Heartbeat** — agent updates `heartbeat_at` every ~15s (or on every tool call, whichever is more frequent).
3. **Collision check** — before any Edit/Write, main session reads `memory/awake/` and warns if another agent claims the target file.
4. **TTL expiry** — if `heartbeat_at` is older than 30s, the record moves to `memory/awake/.stale/`. Stale records are candidates for drain — their progress, if any, feeds the next Dream Cycle.
5. **Drain on clean exit** — on successful completion, Awake record is consumed by the next Dream Cycle: the agent's experience feeds the Consolidate pass.

## Read path

- `boss-awake-status` slash command → tabular report of currently-awake agents
- Main session always reads before spawning a new agent that would touch the same files
- Admin dashboard at `/admin/awake` renders the live view

## Why not SQLite / a daemon / a message bus?

All three were considered. Filesystem won because:

- Survives IDE crashes without a running process
- Git-ignorable (private by default) or Git-committable (shareable state)
- Zero infrastructure — works identically on laptop and server
- Human-readable with `cat memory/awake/<id>.md`
- Trivial to drain into Dream Cycles (already a markdown pipeline)

## Opposite of Dream Cycles

Where Dream Cycles run at night and consolidate experience, Awake runs during the day and captures experience. Together they close the loop:

```
Awake (experience → encode)
  ↓ drain
Dream Cycles (consolidate → replay)
  ↓ integrate
REM + Engram (store → inform future)
  ↓ recollection
Awake (next experience)
```
