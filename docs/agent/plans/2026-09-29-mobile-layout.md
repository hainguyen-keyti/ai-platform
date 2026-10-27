# Plan: the web works on a phone

## 1. Goal

The owner, 2026-09-29, after the design review found the web unusable on a phone: **"ok, làm tiếp
đi"**, then **"Nút ☰ mở danh sách"**, **"Ẩn email trên điện thoại"** and **"Tier 2"**.

Measured 2026-09-29 before any change (`/tmp/mobile_measure.py`, screenshots in
`/tmp/mobile_before/`), at 390x844:

- the chat page is 533px wide on a 390px screen, so it scrolls sideways; the sidebar keeps its
  256px (`web/src/pages/Chat.jsx`, `aside w-64`), the composer is 180px wide and Send sits at
  x=456-521, off the screen
- the gallery page is 474px wide: the nav's email (`web/src/App.jsx`) pushes the language switch
  and sign out off the screen; the gallery grid itself fits
- the login page fits; at 768x1024 nothing overflows

Done means: at 390px wide no page scrolls sideways (a new chat, an open conversation, the
gallery), the composer and Send are fully on the screen, the conversation list is hidden and opens
from a "☰" button in the chat header as a panel over the whole chat, closing when a conversation or
"New chat" is picked (or with its own close button); the nav hides the email below 640px and keeps
the quota, the language switch and sign out on the screen; from 768px up the layout is as today.

## 2. Non-goals

- Any change to the desktop layout, the login page or the gallery grid
- The design review's other points (the reply bubble's blank lines, the select's accessible name)
- New routes, a router, or a component library
- The api and the worker

## 3. Invariants touched and risk tier

None: layout only. No job, quota, conversation or provider path changes; the existing 28 ui checks
at desktop width must stay green.

### Risk tier

**Tier 2**, the owner's choice on 2026-09-29: one code review round and one design-review pass on
screenshots (desktop and mobile, both languages), then acceptance with mutants, no re-review.

## 4. Acceptance evidence

```
~/cloakbrowser-env/bin/python tests/ui_smoke.py   # 31/31 PASSED (28 + 3 new), the three new checks RED first
(cd web && npm run build)                         # ok
python acceptance.py                              # 36/36 PASSED, unchanged
```

The three new checks run in a second browser context at 390x844 with the smoke user's session:
the chat does not scroll sideways and Send is on the screen; the list is hidden, opens from "☰" and
closes when a conversation is picked, which then shows; the gallery does not scroll sideways and
the language switch and sign out are on the screen.

Mutants, each red: the sidebar not hidden on a phone, the chat pane without `min-w-0`, a pick that
leaves the list open, the email not hidden.

## 5. Blast radius

```
web/src/App.jsx
web/src/pages/Chat.jsx
web/src/lib/strings.jsx
tests/ui_smoke.py
```

## 6. Reuse pointers

- `web/src/pages/Chat.jsx`: the `aside` and `section`, the header, the composer form
- `web/src/App.jsx`: the nav
- `tests/ui_smoke.py`: the served-provider checks show how a check gets its own state; the smoke
  user's token is in the page's localStorage
- `/tmp/mobile_measure.py`: the measurement

## Tasks

### T1: Red checks
The three phone checks in `tests/ui_smoke.py`, as in section 4, each red on today's web.
**Files:** tests/ui_smoke.py
**Acceptance:** exactly the three new checks red, for those reasons

### T2: The layout
The sidebar hidden below 768px with a "☰" button and a close button, the list as a full-screen
panel that closes on a pick, `min-w-0` where the chat pane and the composer must shrink, the nav's
email hidden below 640px, the button labels in both languages.
**Files:** web/src/pages/Chat.jsx, web/src/App.jsx, web/src/lib/strings.jsx
**Acceptance:** `npm run build` ok; `tests/ui_smoke.py` 31/31

### T3: Review, design review, mutants, gates, Evidence
One code review round and one design-review pass on screenshots; any fix seen red first; the
mutants; the full gate once.
**Files:** whatever the review names, inside the radius
**Acceptance:** section 4

## Evidence

Closed 2026-09-29 at **ab8e210**, clean tree. Every number is the command's own count line.

| Command | Result |
|---|---|
| Full gate, once: `python acceptance.py && (cd web && npm run build) && tests/ui_smoke.py` | **36/36 PASSED**, build exit 0, **40/40 PASSED**, exit 0, at ab8e210 with the host worker in mock (load average about 70 from other apps) |
| `tests/ui_smoke.py`, T1's three phone checks | red first at 28/31 on a4a36f3 (the chat 533px wide with Send at 456-521; no list button; the gallery 452px with the language switch and sign out off the screen); green at dd430ac |
| `tests/ui_smoke.py`, the review round's seven checks | red first at **31/38** on dd430ac, each for its reason: no header title; 0 copies of a list error in the list; no `aria-expanded`, focus left on ☰, Tab into the chat 5 times, Escape ignored; ☰ 30x30, select 29px, close "×", row buttons 20px tall with no names; every field 14px; the Vietnamese nav 63px with sign out alone; the list's title "Cuộc trò chuyện" and no heading |
| `tests/ui_smoke.py`, wide content | red at **39/40** with the design fixes in and the bubbles as before: the pasted link's first character at x=-286, the thread 298px sideways; now first character at x=28, 0px sideways, page 390 |
| `tests/ui_smoke.py`, two checks for the code review's surviving mutants | Close and New chat close the list, the phone layout ends at 768px (767: button and no list; 768: list and no button) |
| Web mutants (`/tmp/run_web_mutants.py`: a copy of `web/` on port 5174, the served module proven to carry the mutant, the real ui_smoke) | **22 of 22 red**. The plan's four: the sidebar not hidden (34/40), the pane without `min-w-0` (page 737px, Send at 725), a pick leaving the list open, the email shown (nav 81px, "@" in the nav). The code review's five survivors: New chat and Close leaving the list open, `md:` moved to `lg:`, ☰ on a desktop, the nav without `flex-wrap` (survived the first run; killed at ab8e210 once no nav item may wrap its words). The round's own code: Escape in a rename closing the list, widening leaving the list open (chat not usable), no `inert` (Tab into the chat 6 times), the title from the loaded conversation ("Untitled" while it loads), no error in the list, the nav not grouped (split at 320 and 344 in Vietnamese), the brand shown (63px), 16px on a desktop, either bubble as before, focus not moved in, no `aria-expanded`, rows 20px tall |
| Desktop, dd430ac against ab8e210 (`/tmp/mr/desktop_head.py`, every visible box at 768, 1024, 1280 and 1440px, five states) | page widths and field fonts identical; the row's buttons fill the row (20 to 32px tall, the row box and the text unchanged); at 768 the long link now wraps and a code reply keeps 480px instead of 672; Vietnamese with a 46 character email at 768 wraps the whole right side instead of sign out alone; a 1px shift of the quota from 1024 |

Review, tier 2: one code review and one design-review pass on screenshots. The design review found
nothing blocking and fourteen points; the owner chose (DECISIONS 2026-09-29) to fix what the change
caused (the Vietnamese nav, errors under the panel, no sign of the open conversation, two × in one
column, a small ☰, no Escape, focus or aria) plus fields under 16px and rows too small to tap. The
code review found two blocking points, both fixed: a long unbroken string lost its start past the
left edge (up to 286px at 390, 164px at 768), and two of the plan's four mutants survived its
checks.

Deviations: acceptance grew from 31 to 40 checks, the owner's choice, each check seen red first or
proven by a mutant. The Vietnamese quota reads "còn N", not the proposed "còn N lượt": measured, the
longer one put the nav on two rows at 360 and 375px against the one row the owner chose; the right
side of the nav wraps as one group. The plan's "the gallery grid itself fits" was measured on an
empty gallery: with files a card runs over the next tile (parked); its check is renamed to what it
measures. Two of `/tmp/mobile_before/` (390-login, 390-new-chat) were overwritten at 14:07 by a rerun
of the measurement after the change; the rest date from 13:58 and T1's red run is the proof of the
before. "view follows new messages" failed once more in a mutant run under load (432px from the
bottom, as on 2026-09-29 before); parked.

Left open, parked in HANDOFF: the phone's Back button, the reply's blank lines, slate-400 contrast,
an empty list's blank panel, the gallery's file card, the placeholder at 16px (English cut by 8px at
390), the header title squeezed while a provider is unserved, the nav breakpoint at 640 against the
chat's at 768.
