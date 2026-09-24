# ChatGPT provider measurements, 2026-09-24

What the site did when asked, recorded from `tests/provider_probe.py` run against the saved
session, with the host worker stopped. Every line below is a printed measurement, not a reading of
the site's code. Rerun the probe when the site changes; the numbers are the day's, not forever.

## The requests a turn makes

`send`: one turn ("Reply with the single word: ok") fired these POSTs, in order:

```
/backend-api/sentinel/chat-requirements/prepare
/backend-api/aip/connectors/links/list_accessible
/backend-api/conversation/init
/backend-api/f/conversation/prepare
/backend-api/sentinel/chat-requirements/finalize
/backend-api/apps/availability
/backend-api/onboarding/recommendations
/backend-api/f/conversation          <- the streaming turn request
/backend-api/sentinel/ping
/backend-api/sentinel/req
/backend-api/lat/r
```

The turn settled on the server's word in 14s. The last assistant turn was saved as
`tests/fixtures/chatgpt_reply.html` (7437 chars, no address-like strings) as the negative case
for the banner detector.

## The DOM fallback and the settle floor

`dom-settle`: with every `GET /backend-api/conversation/<id>` answered 500 from inside the page,
the provider gave up on the server view after 12 withheld reads and settled on the page:
`settle=dom`, success, 54s, text `dom fallback check`. Read afterwards with the server view back,
the server's text was identical to what the page had given.

Timeline of an ordinary turn watched at 4Hz: stop button seen at +0.3s, gone at +3.9s, last text
change at +2.3s. The text stopped changing 1.6s before the button left; `SETTLE_SECONDS = 6` of
quiet after the button leaves is more than the measured need for a reply of 104 chars. Long or
tool-using replies were not timed here.

## Where the memory switch lives

`memory`: no JSON read before the toggle showed a memory flag by name. `/backend-api/settings/user`
carried only an onboarding timestamp; `/backend-api/memories` lists the saved memories themselves
(user text; the probe now prints only their count, which was 10, all from the 2026-09-23 tests)
with `memory_num_tokens 1348` and `memory_max_tokens 5000000`, but no on/off state; `/backend-api/accounts/check/v4-2023-04-27`, `/backend-api/me`,
`/backend-api/user_system_messages` and `/backend-api/settings/beta_features` had nothing either.
A brand new conversation reported `memory_scope: "global_enabled"` while the switch was off, so
that field says nothing about the account setting.

The Personalization pane (`https://chatgpt.com/#settings/Personalization`) shows five switches;
read through `aria-labelledby`: Fast answers on, Suggested prompts on, Enable memory off, Reference
my writing style off, Reference record history off.

`memory-toggle` (run once, by name, worker stopped, no turn sent while on): clicking Enable memory
fired `PATCH /backend-api/settings/account_user_setting?feature=m3m&value=true` and
`POST /backend-api/memories/about_you/summary/stream?source=personalization-setting`; no
confirmation dialog. `GET /backend-api/settings/user` then changed in exactly three places:
`settings.m3m`, `settings.sunshine`, `settings.moonshine`, all false to true. Clicking again fired
the same PATCH with `value=false`; the switch read off and the JSON matched the original snapshot
with no difference. The worker's guard reads `settings.m3m`, `sunshine` and `moonshine` once per
job, before sending; any true means on; all present and false means off; anything else (keys
missing or null) means unknown, which is reported, not treated as on. No session token at all is
a logged-out session and the turn is refused; a token the server answers 401 to is replaced once
and the read repeated, so a stale credential never lets a turn through unchecked (review finding,
2026-09-24).

## What a failed turn looks like

`banner`: with every POST to `/backend-api/*conversation*` answered 500 from inside the page (3
requests failed), the site painted:

```
DIV  class="text-token-text-error border-token-surface-error/15 bg-token-surface-error/5 flex
            items-center gap-6 rounded-2xl border text-sm px-3 py-2.5 md:p-4 mb-2 w-full ..."
     text: "<the server's detail message>Retry"
BUTTON "Retry" inside it
```

No `role="alert"`. The container `#thread-bottom-container` carries Tailwind variants named
`has-data-has-thread-error:*`, but no element carried the bare `data-has-thread-error` attribute
inside `main`. The banner's text is the server's own `detail` string, so it arrives in whatever
wording and language the failure had; matching words would be matching the server's mood. The
detector `ERROR_BANNER_PRESENT` therefore matches shape: a `.text-token-text-error` element inside
`main` that holds a button and has text. Saved as `tests/fixtures/chatgpt_error_banner.html`
(18911 chars, no address-like strings); the two negative fixtures, the assistant turn alone and
the whole `main` of a healthy page with its composer, have zero occurrences of that token. The
detector compares against the banner text seen before the turn was sent, so a banner left over
from an earlier turn in a reused thread is not read as this turn's failure.

After the failure the address read `https://chatgpt.com/c/WEB:<uuid>`: a client-side placeholder
the server does not know. `_thread_id` now treats `WEB:` ids as no thread, so a failed first turn
can never be stored as a conversation's thread.

## Deleting a thread

`cleanup`: `PATCH /backend-api/conversation/<id>` with `{"is_visible": false}` answered 200
`{"success": true}`; `GET` of the same id answered 404 afterwards. This is the call the trash
feature in the next plan can use to take a deleted platform conversation out of the shared
account's Library. Only the probe's own thread was deleted.
