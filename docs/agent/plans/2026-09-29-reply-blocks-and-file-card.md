# Plan: replies without blank lines, file cards inside their tiles

## 1. Goal

The owner, 2026-09-29: **"ok, làm tiếp đi"**, then **"Cả hai lỗi hiển thị"** and **"Tier 3 + ảnh
trước/sau gửi anh"**.

Measured 2026-09-29 (`/tmp/polish_probe.py`, the conversation and the gallery answered in the
browser, nothing sent anywhere):

- the reply bubble has `whitespace-pre-wrap` on the whole of it (`web/src/pages/Chat.jsx:33`), so
  the line breaks react-markdown puts between blocks and between list items show as blank lines:
  one line, a three item list and one line take **246px**; three bullets **166px**; one line, a two
  line code block and one line **146px**. Those blank lines are also the only thing that separates
  two paragraphs today (`p` has no margin)
- a file card is a fixed `w-64` (`web/src/components/FileCard.jsx:38`): in the gallery's two
  columns on a phone it runs out of its tile (at 390px the card is at 212-468 in a tile at
  203-366; at 320px 177-433 in 168-296)

A prototype (`/tmp/polish_prototype.py`: `pre-wrap` only inside paragraphs and an even 8px between
blocks; the card `w-full max-w-64`) measured 134, 78 and 114px, a paragraph's own line break kept
and two paragraphs 8px apart; the card inside its tile at 390 and 320px, and still 256px in the
chat.

Done means: a reply shows its blocks with no blank lines between them or between list items,
paragraphs stay apart and keep their own line breaks; a file card never leaves its gallery tile,
and the chat's card is unchanged.

## 2. Non-goals

- Headings, tables and blockquotes in replies
- The person's own bubble (it keeps its `pre-wrap`)
- The gallery grid itself (columns, padding) and pictures
- Anything else parked

## 3. Invariants touched and risk tier

None: display only; no job, quota, conversation or provider path changes.

### Risk tier

**Tier 3**, the owner's choice on 2026-09-29: no separate review; acceptance with five mutants,
and before and after screenshots sent to the owner.

## 4. Acceptance evidence

```
~/cloakbrowser-env/bin/python tests/ui_smoke.py   # 45/45 PASSED (43 + 2 new), the two new checks RED first
(cd web && npm run build)                         # ok
python acceptance.py                              # 36/36 PASSED, unchanged
```

The two new checks answer everything in the browser: a reply's blocks at 1280px (the list reply at
most 150px, three bullets at most 90px, the first paragraph keeping its two lines, a gap of 4 to
16px between two paragraphs); every file card inside its gallery tile at 390 and 320px, and the
chat's file card still 256px. "media sits inline in the timeline" finds bubbles by
`.whitespace-pre-wrap`; it moves to their `data-testid`s, measured first to pick the same elements
on today's web.

Mutants, each red: `pre-wrap` back on the whole bubble; no `pre-wrap` in paragraphs; no gap between
blocks; the card back to `w-64`; `w-full` without `max-w-64`.

## 5. Blast radius

```
web/src/pages/Chat.jsx
web/src/components/FileCard.jsx
tests/ui_smoke.py
```

## 6. Reuse pointers

- `/tmp/polish_probe.py`: the measurement (the answered routes, the replies, the gallery)
- `/tmp/polish_prototype.py`: the fix as measured
- `tests/ui_smoke.py`: the tail checks' second context and their `answer` routes; `png()`

## Tasks

### T1: Red checks
The two checks in `tests/ui_smoke.py`, as in section 4, each red on today's web for its reason; the
"media sits inline" check moved to the bubbles' `data-testid`s once the two selectors are measured
to pick the same elements today.
**Files:** tests/ui_smoke.py
**Acceptance:** `tests/ui_smoke.py` with exactly the two new checks red

### T2: The fix
The reply bubble's classes and the file card's width, as measured in the prototype.
**Files:** web/src/pages/Chat.jsx, web/src/components/FileCard.jsx
**Acceptance:** `npm run build` ok; `tests/ui_smoke.py` 45/45

### T3: Mutants, gates, screenshots, Evidence
The five mutants; the full gate once; before and after screenshots to the owner.
**Files:** whatever a surviving mutant shows missing, inside the radius
**Acceptance:** section 4

## Evidence

Closed 2026-09-29 at **bbb3924**, clean tree. Every number is the command's own count line.

| Command | Result |
|---|---|
| Full gate, once: `python acceptance.py && (cd web && npm run build) && tests/ui_smoke.py` | **36/36 PASSED**, build exit 0, **45/45 PASSED**, exit 0, at bbb3924 with the host worker in mock |
| `tests/ui_smoke.py`, the two new checks | red first at **43/45** on 9d3a60b (667535a), exactly the two: list 246px, bullets 166px, 20px between two paragraphs (the first paragraph two lines, 40px); every file card out of its tile at 390 and 320px, the chat's card 256px. Now list 134px, bullets 78px, 8px between paragraphs, the first paragraph still 40px; every card inside its tile, the chat's card 256px |
| "media sits inline in the timeline", moved off `.whitespace-pre-wrap` | measured before the move (`/tmp/selector_equivalence.py`): the class and the two test ids pick the same nine elements in the same order on 9d3a60b; green before and after the fix |
| Web mutants (`/tmp/run_look_mutants.py`: a copy of `web/` on port 5174, the served module proven to carry the mutant, the real ui_smoke) | **5 of 5 red**, each on its own condition: `pre-wrap` back on the bubble (list 254px, gap 28px), no `pre-wrap` in paragraphs (the first paragraph 20px), no gap between blocks (0px), the card back to `w-64` (out of its tiles), `w-full` without `max-w-64` (the chat's card 992px) |
| After, the same probe and data as before (`/tmp/polish_probe.py`) | replies 134, 86, 78, 114 and 38px against 246, 98, 166, 146 and 38 before; the chat's file card 256px at 1280 and 390; every gallery card inside its tile at 390 and 320px, unchanged at 1280. Before and after screenshots (`/tmp/look_before/`, `/tmp/look_after/`) sent to the owner |

Tier 3, the owner's choice: no separate review. No deviation from the plan.
