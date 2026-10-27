# Plan: Grok reads its memory switch before every turn

## 1. Goal

The owner, 2026-09-27, after the measurement that Grok's memory was on: **"Tắt memory rồi thêm
guard"**, **"Tôi cho phép bạn tắt"**, **"Chỉ thử sau khi tắt"**; then, for this plan, **"Chỉ thử rò
rỉ"** and **"Tier 2"**.

Measured 2026-09-27, read-only, then the one approved change: `GET /rest/user-settings` from inside
grok.com answered `enableMemory: true` (beside `allowGrokFinishedNotification`,
`agentCustomizations`, `mutedBotPushAgentIds`). The switch is Settings, Data Controls, "Personalize
Grok with your conversation history" (Beta: "Allow Grok to remember details from your previous
conversations"). The agent turned it off with the owner's permission: the page sent
`POST /rest/user-settings {"enableMemory": false}` and the read back said `false`. Nothing in the
worker reads it (`grok.py` has no memory read, `_run` at `grok.py:411` sends right after `_open`),
and the gate skips the grok memory check as "a chatgpt account setting" (`acceptance.py:96-97`).

Done means: before every Grok turn the driver reads `enableMemory` through its in-page fetch
(`grok.py:151` `_api`, no extra page load); `true` refuses the turn before anything is sent
(provider_misconfigured, refunded), `false` lets it go, anything else reads `unknown` and does not
block; health shows the reading in the existing `memory` field; the real grok gate no longer skips
"health reports the provider's memory setting"; and with memory off, a word told in one Grok
conversation does not come back in a new one.

## 2. Non-goals

- Any other Grok setting: "Improve the Model" and "Allow chat link sharing" stay as they are
- Turning memory on again, or a leak test with it on
- The ChatGPT and Gemini drivers, the pool, the runner, the api and the web
- A new health field, or a page load per turn for the read
- The rule that an unreadable switch reads `unknown` and does not block (DECISIONS)
- The whole real grok gate (the owner's choice: it costs about ten of the free tier's seven or so
  daily turns)

## 3. Invariants touched and risk tier

- **Isolation.** A turn is never sent while the shared Grok account's memory reads on; `unknown`
  does not block, as decided for ChatGPT and Gemini
- **Quota.** A refused turn is refunded exactly once, through the existing provider_misconfigured
  path
- **One job, one turn.** The read is a fetch, never a second send

### Risk tier

**Tier 2**, the owner's choice on 2026-09-27: one review round by a separate reviewer; after fixes,
acceptance with mutants, no re-review.

## 4. Acceptance evidence

```
~/cloakbrowser-env/bin/python tests/test_grok_memory.py   # N/N PASSED; red first on the current driver (no memory read)
~/cloakbrowser-env/bin/python tests/test_grok_settle.py   # 8/8 PASSED, unchanged
python acceptance.py                                      # 34/34 PASSED, unchanged
```

Mutants on a copy, each red: the read removed from `_run`, the key misread, `on` still sending,
`unknown` blocking.

Real, two Grok turns through the new driver (`/tmp/grok_leak_probe.py`): each turn's reading is
`off`, and a word told in conversation A does not come back in a new conversation B. Then the host
worker serves grok again (`PROVIDERS=chatgpt,grok,gemini`) and its health shows grok ready.

## 5. Blast radius

```
worker/src/providers/grok.py
tests/test_grok_memory.py
acceptance.py
docs/research/2026-09-25-grok-measurements.md
```

## 6. Reuse pointers

- `worker/src/providers/chatgpt.py:431-467` `_read_memory`, and `:738-741`, the refusal right
  after `_open`, before anything is sent
- `worker/src/providers/gemini.py` `_guard`, and the whole-turn cases in `tests/test_gemini_driver.py`
- `worker/src/providers/grok.py:151` `_api`, the in-page fetch the read uses
- `worker/src/pool.py:221-222`: health already reads `memory` from any provider
- `tests/test_grok_settle.py`: a stub page answering the Grok driver's `evaluate`

## Tasks

### T1: Red tests and the measurement
`tests/test_grok_memory.py` on a stub page: `enableMemory` true reads on, false off, a missing key
or a failed read unknown; a turn with memory on is refused as provider_misconfigured before anything
is sent, while off and unknown let the send happen; the provider's `memory` shows the last reading.
The research note records the switch, the endpoint, the change, and the two switches left on.
**Files:** tests/test_grok_memory.py, docs/research/2026-09-25-grok-measurements.md
**Acceptance:** `tests/test_grok_memory.py` red on the current driver, for that reason

### T2: The driver and the gate
`GrokProvider._read_memory(page)` through `_api`, called in `_run` right after `_open`, refusing on
`on`; `acceptance.py` drops the grok REAL_SKIPS entry for the memory health check.
**Files:** worker/src/providers/grok.py, acceptance.py
**Acceptance:** `tests/test_grok_memory.py` N/N; `tests/test_grok_settle.py` 8/8;
`python acceptance.py` 34/34; the four mutants red

### T3: Review, the real leak test, Grok back on the host worker, Evidence
One review round (tier 2); any fix seen red first; then two real turns through the driver, then
the host worker restarted with grok and its health read.
**Files:** whatever the review names, inside the radius
**Acceptance:** section 4

## Evidence

Closed 2026-09-27 at **20f1aad**, clean tree. Every number is the command's own count line.

| Command | Result |
|---|---|
| `tests/test_grok_memory.py` | **17/17 PASSED**; red first at 0/12 on 743a586 (no memory read in the driver; a turn with memory on was sent, `sent ['hello']`; `memory` None) |
| `tests/test_grok_settle.py` | **8/8 PASSED**, unchanged |
| Full gate, once: `python acceptance.py && (cd web && npm run build) && tests/ui_smoke.py` | **34/34 PASSED**, build ok, **25/25 PASSED**, exit 0, at 20f1aad with the host worker in mock |
| Mutants (`/tmp/run_grok_mutants.py`, on a copy) | **9 of 9 red**: the plan's four (the read removed, the key misread, on still sending, unknown blocking), the refusal as provider_error, and the review's four survivors once the review's cases were added (read once then reused, no reset before the read, the read turned into a POST writing `enableMemory`, the except narrowed so a list body crashed the turn) |
| Real, two Grok turns through the driver (`/tmp/grok_leak_probe.py`) | turn A (new conversation, "Remember this word for later: teal-...") `success=True memory=off` "ok" in 17.3s; turn B (another new conversation, asked for the word) `success=True memory=off` "Unknown" in 15.5s; separate threads, the word did not come back. `GET /rest/user-settings` carries no cache-control, expires, pragma, etag or last-modified header |
| Host worker | restarted in real mode at 20f1aad with `PROVIDERS=chatgpt,grok,gemini`: all three `ready` |

Review, tier 2: one round by a separate reviewer. Nothing blocking: the read comes right after
`_open` and before anything is sent on every path (`_run` is the only sender; `chat` and
`generate_image` reach it, video script raises), twenty odd answers all read `unknown` without
crashing, and the refusal is refunded exactly once. Its four surviving mutants were test gaps,
closed in a9e03c1 and each seen red. Its point on the browser's cache was measured above; its point
that the plan's Evidence was empty until the real run is answered by the two turns.

Deviation: none. Real Grok turns spent: two. The leak test's threads stay in the account like the
other test threads (ae9f4f6b, 7b95db0b).

Afterwards, 2026-09-28, at the owner's word: `python acceptance.py --real --provider grok --keep` at
20f1aad, clean tree, host worker without grok while it ran: **18/18 PASSED, 16 skipped, exit 0**,
with "health reports the provider's memory setting" now run and reading `memory off` (17/17 with 17
skipped before this plan). The image conversation's thread was deleted on the first attempt; four
test threads stay.
