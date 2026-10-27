# Plan: two gate checks measure the thing itself

## 1. Goal

The owner, 2026-09-29: **"ok, làm tiếp đi"**, then **"Duyệt, tier 2"**.

Two checks in `acceptance.py` can pass for the wrong reason:

- the two thread deletion checks (`acceptance.py:673-677`, `726-730`) wait for the worker's total
  `threads_deleted` (`acceptance.py:623-625`) to grow by one, not for the thread they deleted: a
  slow deletion from the first check landing in the second one's window would turn it green (the
  busy-runner review, 2026-09-29)
- "threads never cross conversations" (real mode, `acceptance.py:476-485`) only demands that the
  secret is absent from the fresh conversation's reply, so a failed or empty turn passes: in the two
  Gemini real runs of 2026-09-29 that failed every turn (the session signed out, then personal
  context on; workspaces ai-platform-acceptance-mfsl4l1w and -eaeggvnx) it read PASS

Done means: the first deletion check waits for the tombstone of the deleted conversation's own
thread (its `provider_thread_url`, read from the api's database before the delete) to be marked
deleted; the second waits for a tombstone of this provider that did not exist before its delete to
be marked deleted; "threads never cross conversations" passes only on a finished turn with a
non-empty reply that lacks the secret.

## 2. Non-goals

- Any other check, the gate's order or its waits
- The api, the worker, the tombstone queue

## 3. Invariants touched and risk tier

None in the product: the gate only reads the api's database (read-only, WAL) and demands more
before it passes; no check is loosened.

### Risk tier

**Tier 2**, the owner's choice on 2026-09-30: one code review round; acceptance with mutants; no
re-review.

## 4. Acceptance evidence

```
python acceptance.py                                   # 36/36 PASSED, unchanged
~/cloakbrowser-env/bin/python /tmp/replay_cross.py     # the new cross-conversation rule on the two kept Gemini runs: red
```

Red first: a mutant api whose tombstone for a deleted conversation carries another url (the worker
still deletes, so the total grows) runs the mock gate on a copy of the repo: the old deletion check
green, the new one red. The new cross-conversation rule, replayed on the two kept Gemini
workspaces' job records, is red where the old one read PASS. No real turn is spent.

Mutants, each red: the wrong-url tombstone above; the second check counting any tombstone; the
cross-conversation rule without the non-empty demand (replayed).

## 5. Blast radius

```
acceptance.py
```

## 6. Reuse pointers

- `acceptance.py`: `threads_deleted`, `job_state`, `wait_state`, the deletion checks, `chat_once`
- The kept workspaces of 2026-09-29 (db/app.db of each)

## Tasks

### T1: Red evidence
The wrong-url mutant on a copy (mock gate: the old deletion check green) and the replay of the old
and new cross-conversation rules on the two kept Gemini workspaces.
**Files:** none in the repo (copies and /tmp)
**Acceptance:** the mutant copy's gate reports the deletion check green; the replay shows the old
rule PASS and the new rule FAIL on both workspaces

### T2: The checks
`db_path` into `run_checks`; the deletion checks by their own tombstones; the cross-conversation
check demanding a finished, non-empty reply.
**Files:** acceptance.py
**Acceptance:** `python acceptance.py` 36/36; the mutant copy with the new gate: the deletion check red

### T3: Review, mutants, full gate, Evidence
One code review round; the mutants; the full gate once.
**Files:** whatever the review names, inside the radius
**Acceptance:** section 4

## Evidence

Closed 2026-09-30 at **89e8beb**, clean tree. Every number is the command's own count line.

| Command | Result |
|---|---|
| Full gate, once: `python acceptance.py && (cd web && npm run build) && tests/ui_smoke.py` | **36/36 PASSED**, build exit 0, **45/45 PASSED**, exit 0, at 89e8beb with the host worker in mock |
| Red first, the old gate (34b533c) on a copy whose api tombstones another url (`/tmp/run_gate_mutant.py`) | deletion check **PASS** "provider threads deleted 0 -> 1", 36/36, while the conversation's own thread was never deleted |
| Red first, the old cross-conversation rule replayed on the kept Gemini runs (`/tmp/replay_cross.py`) | signed-out run and personal-context-on run: a failed, empty fresh turn, old rule **PASS**, new rule FAIL; the green run PASS under both |
| Gate mutants on copies, the final gate (`/tmp/run_gate_mutants3.py`) | the api settling its own tombstones with the worker never deleting (the review's blocking finding): both deletion checks **red**, 33/36; the delete tombstoning another url: the deletion check red, 35/36; no tombstone for a cancelled turn's thread: the cancel check red, 35/36; a database path that does not exist: both red, 34/36, the gate printing its summary (no crash) |
| The cancel check's snapshot (`/tmp/run_gate_mutant2.py`, the first version) | with no tombstone for the cancelled turn, the gate red; the same gate counting any deleted tombstone green 36/36: the snapshot is what catches it |

Review, tier 2: one blocking finding, fixed and proven by its own mutant (the first version trusted
the api's `deleted_at` alone and lost the worker's own evidence, a loosening the plan ruled out;
now a deletion needs the worker's count grown and the api's record of a new tombstone for this
thread, claimed and settled); a database read error no longer ends the whole gate, and the path is
a required argument. Its notes, taken: the cancel check's detail says what it measures (a thread
tombstoned after its delete, not "the turn's own", which the gate cannot learn); check 1 snapshots
its tombstones too.

Deviations: the cancel check's wait runs only when its turn was sent (it waited 150s for nothing on
grok real runs since the previous plan). The replayed rule's partial mutants (only "done", only
"non-empty") are not told apart by the kept runs, whose failed turns are both failed and empty.
