# LESSONS.md: project lessons (read before similar work)

Each lesson is 1-3 lines: what happened, the cause, the right way, with an absolute date.
A lesson that repeats a second time is promoted to a rule in CLAUDE.md or to a hook, then deleted
from here. Keep this file under 40 lines.

## Lessons
- 2026-09-23: Guessing which property tells two page elements apart cost five wrong answers in one
  day; on 2026-09-24 a JSON field whose name sounded right (memory_scope "global_enabled") read the
  opposite of the switch. Print the attributes, or flip the switch and watch the wire.
- 2026-09-23: A suite that speaks one language, or sits in one seat, cannot see a class of defect.
  File capture matched "Download" and dropped files for anyone typing Vietnamese; a mutant removed
  the delete route's ownership clause and stayed green, because only the owner ever deleted.
- 2026-09-24: Server truth is not free: reading the conversation endpoint every 1.5s drew a 429 that
  bounced thread pages to the root, as did a gate firing turns with no gap. A few reads per turn, paced.
- 2026-09-24: A silent fallback that keeps the request "working" can be worse than a failure. A slow
  thread page fell back to a fresh chat and gave a confident wrong answer that only a recall check
  caught. Fall back on a definitive signal only (404); otherwise fail visibly, retry, refund.
- 2026-09-25: The second provider repeats the first one's traps, so port the guards, not just the
  shape. A turn is done when it carries words or a picture, never on a flag alone, and its answer is
  a bubble that was not there before: text that stopped changing can be the PREVIOUS answer.
- 2026-09-25: The gate mocks the provider boundary and never loads the driver: three blocking defects
  shipped green. A driver is proven by a probe on the real site; a fake page proves only what it
  models (2026-10-02: one that painted at once and reused one tab let 26 of 36 mutants through;
  2026-10-06: one whose "Add files" opened the upload, a guess, passed while the real one opened nothing).
- 2026-09-23 to 10-22 (kt rule §4): the ruler lied first: a 60s wait on a 150s gap, `17/15 PASSED`,
  `echo` exit 0 on a red gate, a list's first load racing the send, a test's own half-pixel scroll, a
  mutant runner copying mid-run edits (twice), the dev build's doubled first read, a health page taken
  for serving. Read the count; set the state up; emulate nothing real never does; edit only between runs.
- 2026-09-27: Gemini threads deleted back to back drew Google's CAPTCHA on this IP. Pace bulk
  account actions minutes apart; stop at a non-site page.
- 2026-10-01: Each launch a new device on login-day cookies: a Gemini login died in 47m. A profile
  and a pinned seed kept the next through 7 launches in 2h15; ChatGPT's Cloudflare check still came.
- 2026-10-02: Every ChatGPT picture took "the ceiling and a little" and the agent raised the
  ceiling. A wait that always ends at its limit is the limit, not the work: watch the thing
  (the picture was there at 22s) before moving a number.
- 2026-10-06/07: A UI check failed 2 times in 17 on a console error with no address; four guessed
  mechanisms and 13 more runs found nothing. Once the error carried its address and step, the next
  failure named it (a gallery left at once) and it reproduced 3 of 3. Make a flake say where first.
