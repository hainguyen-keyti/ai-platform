# 2026-10-21: the state measured after twelve idle days (HEAD 4cd26c8, clean tree)

The owner asked for a thorough review of the plans and the source before work continues. These are
the agent's own measurements of the day; the four reviewers' reports sit beside this file.

## The tree and the services

- `master` at 4cd26c8 = `origin/master`, clean; no plan armed; nothing in the repo modified since
  2026-10-09 (the last commit).
- api and web containers up ("Up 2 weeks"), both answering 200. The host worker was down (it ends
  with the desktop app); started again at 18:5x in the app's Terminal tab "host worker (real)",
  `PROVIDERS=chatgpt,grok,gemini`, output in `/tmp/host-worker-real-90.log`; `/health` real, 4cd26c8,
  all three ready.
- The live database: 1401 jobs, 230 users (ui_smoke and the gate register one each run), 73
  conversations, 70 media, 14 live API keys of test users (ui_smoke leaves a "phone key" per run),
  12 dead tombstones (mock threads of September, four Gemini threads of 2026-10-01 that no longer
  exist), one expired Grok hold of 2026-10-01. Test data, by the stage.
- `storage/`: media 70 MB, db 4.2 MB, profiles chatgpt 186 MB, gemini 313 MB, grok 64 MB;
  `storage/diagnostics` empty.

## The gate and every offline suite (`/tmp/run_full_gate_offline.sh`, a mock worker started and
## stopped by the script, 18:54 to 19:0x)

| Suite | Result |
|---|---|
| `python acceptance.py` | **54/54 PASSED** exit 0 |
| `npm run build` | exit 0 |
| `tests/ui_smoke.py` | **59/59 PASSED** exit 0 |
| `tests/test_chatgpt_composer.py` | 51/51 |
| `tests/test_gemini_driver.py` | 143/143 |
| `tests/test_grok_settle.py` | 8/8 |
| `tests/test_grok_memory.py` | 20/20 |
| `tests/test_tombstones.py` | 5/5 |
| `tests/test_runner_health.py` | 4/4 |
| `tests/test_runner_liveness.py` | 4/4 |
| `tests/test_runner_tombstones.py` | 3/3 |
| `tests/test_login_provider.py` | 10/10 |
| `tests/test_session_profile.py` | 12/12 |
| `tests/test_dom_signatures.py` | 10/10 |

Tree unchanged after; the mock worker stopped, port 8000 closed before the real one was started.

## The three sessions, read-only (`/tmp/session_alive.py`: each profile opened headless, the
## login script's own proof asked inside the page, no turn sent, no value printed)

| Provider | Reading | Note |
|---|---|---|
| ChatGPT | signed in: the session cookie present, `/backend-api/settings/user` answered 200 with the page's own token, no login control on the page | the first look read "signed out": its proof ran 5 s after `domcontentloaded`, before the page's session read was ready; two later looks (17 s and a detailed one) read signed in. The ruler, not the account |
| Grok | signed in: `sso-rw` and `/rest/app-chat/conversations?pageSize=1` answered | 8 s |
| Gemini | signed in: `__Secure-1PSID` and `/personalization-settings` stayed put | 14 s |

No bot check on any of the three home pages (no "just a moment", "verify you are human", no
`/sorry/`). So the twelve idle days did not end a session: a point for the one-profile plan's lead.

## The drivers' page elements, read-only (`/tmp/selectors_alive.py`: each home loaded, the
## driver's own selector constants counted, nothing typed)

| Provider | Composer | Other elements |
|---|---|---|
| ChatGPT | found after 4 s (`div.ProseMirror[contenteditable="true"]`) | `UPLOAD_INPUT` 2; `SEND_BUTTON` 0 on an empty composer (the driver sends with Enter and uses the button only as a fallback, `chatgpt.py` `_send`); no stop button, as nothing ran |
| Grok | found after 8 s (the first two alternatives of `COMPOSER`) | the two textarea alternatives 0, as for this account's cohort |
| Gemini | found after 16 s | `UPLOAD_CONTROL[0]` and `[1]` 1 each; `UPLOAD_INPUT` 0 until the menu is pressed, as measured on 2026-10-06 |

Screenshots: `/tmp/<provider>-home-2026-10-21.png` (they vanish with `/tmp`'s three-day cleaner).

## What is gone

Every file the plans' Evidence cites under `/tmp` or `$TMPDIR` is gone (macOS removes files unused
for three days): the probe scripts, the worker logs, `/tmp/manual-test-account.json`, the mutant
runners, the kept gate workspaces. The plans' Evidence text is the only record of those runs.
