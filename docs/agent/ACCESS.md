# ACCESS.md: the project's access map (NEVER holds a secret value)

This file only holds paths, names and how to get in. Secret values (keys, passwords, tokens) live
in a gitignored env file or a key file: write the LOCATION, never the value. If the repo may become
public, move sensitive hosts to a gitignored ACCESS.local.md.

## Servers and infrastructure

| What | Command to get in | Where the key lives |
|------|-------------------|---------------------|
| Local Docker | docker compose up | N/A |
| Production | TBD | TBD |

## Services and URLs

| What | URL | How to sign in |
|------|-----|----------------|
| ChatGPT | https://chatgpt.com | Browser profile `storage/sessions/chatgpt/` |
| Grok | https://grok.com | Browser profile `storage/sessions/grok/` |
| Gemini | https://gemini.google.com | Browser profile `storage/sessions/gemini/` |
| Code | https://github.com/hainguyen-keyti/ai-platform (private, branch `master`, since 2026-10-01) | `gh` and git over https, signed in as the owner on this machine |

Since 2026-10-01 (d30caa0, 5ac5ebe) a provider's session is a Chromium profile directory with its
device seed in `device-seed` inside it, opened through `worker/src/providers/session.py` by the
login script, the drivers, the probes and the gate's own worker: the same device at every launch,
and one browser at a time (Chromium refuses a second one; the refusal names the provider). Before
that it was a state file `storage/sessions/<provider>.json` loaded by a new random device at each
launch; those files are no longer read.

`~/cloakbrowser-env/bin/python scripts/login_provider.py <provider>` (the venv python: the plain one
has no cloakbrowser) opens that profile with a window on the provider's own site, waits for the
session cookie and for the account to answer, then closes the window; the session stays in the
profile. Take the provider off the host worker first. Only this script creates a profile; a new
device means deleting the profile directory (the owner's call) and logging in again.
Grok must be logged in on **grok.com**: a session made on x.com/i/grok carries x.com cookies
only and grok.com stays signed out. Its cookie is `sso` on grok.com and its proof
`/rest/app-chat/conversations?pageSize=1` answering 200. ChatGPT's cookie is
`__Secure-next-auth.session-token`, kept in chunks `.0` and `.1`, and its proof
`/backend-api/settings/user` answering 200 to the session's own token (a profile keeps the cookie
of a session the site has ended). Gemini's cookie is `__Secure-1PSID` on google.com and its proof
the settings page staying put (`/personalization-settings`; anyone else is sent to `/saved-info`).

The free Grok tier answers a short burst, then asks for about nine minutes; fully spent it says 22
hours. No endpoint reports this: `/rest/rate-limits` keeps reading 7 of 7. The only reading is the
sentence on the page, which the worker quotes when it refuses.

## Where secrets live

| Name | Location | Used for | Least privilege |
|------|----------|----------|-----------------|
| JWT_SECRET | .env | API auth tokens | Local only |
| Browser sessions | storage/sessions/<provider>/ (a browser profile, git-ignored with all of storage/) | Provider auth | Opened by the worker, the login script, a probe or a gate, one at a time |
| Old state files | storage/sessions/<provider>.json | Nothing since 2026-10-01; Grok's still holds a live login | Deleting them is the owner's call |

## Provider account settings that must stay as they are

| Setting | Required | Why |
|---------|----------|-----|
| ChatGPT, Personalization, Enable memory | OFF | Measured on 2026-09-23: with it on, a fact from one platform conversation was recalled in another, which across users is one person reading another's data |
| ChatGPT, Personalization, Reference record history | OFF | Same leak by a second route |
| Grok, Settings, Data Controls, "Personalize Grok with your conversation history" (`enableMemory` in `GET /rest/user-settings`) | OFF | Measured 2026-09-27: it was ON ("Allow Grok to remember details from your previous conversations"). Turned off by the agent with the owner's permission, that switch only: the page sent `POST /rest/user-settings {"enableMemory": false}` and a read back said `false`. Since 7555b93 the driver reads it before every turn and refuses while it is on (provider_misconfigured, refunded). With it off, a word told in one conversation came back "Unknown" in a new one. On in the same section and left alone (not the owner's question): "Improve the Model" and "Allow chat link sharing" |
| ChatGPT, the account logged in on 2026-10-01 20:14 (a new account, the owner's word) | memory OFF | The driver read `off` before its first turn on that account (16:35, the gate's worker) and before every turn since (`settings.m3m`, `sunshine`, `moonshine`, none true). Still to ask it: "Tôi tên gì?" (the old account answered "Keyti") |
| Grok, the account logged in on 2026-10-01 20:13 (through Google sign-in) | `enableMemory` OFF | The driver read it ON at 20:27 and refused the turn (the provider was held out, as designed). The owner allowed the agent to turn it off; at 21:07 `GET /rest/user-settings` already read `false`, so the agent changed nothing (who turned it off is not on record). Read beside it, left alone: `allowXPersonalization` false, `excludeFromTraining` true, `allowAutoShare` true, `allowShareIndexing` false |
| Gemini, personal context (`gemini.google.com/personalization-settings`) | OFF | Measured 2026-09-25: it was ON, and the page says in its own words that Gemini learns from earlier conversations. Turned off with the owner's permission, proven by a reload reading `aria-checked="false"`. With it off, a word told in one conversation came back "Unknown" in a new one while the same thread still recalled it. The driver reads it before every turn since the Gemini plan (bbeb471) and refuses while it is on |
| Gemini, account `ke***2@gmail.com` (logged in again on 2026-10-01 20:16, into its profile; plan PRO) | personal context OFF | Read ON at 15:21, turned off at 15:49 with the owner's permission; it held through that day's sign-out and the new login (read `false` at 20:25; the worker reads `off` before every turn) |
| Gemini, saved info (`gemini.google.com/saved-info`, the switch `Enables or disables the saved info feature`) | OFF | Read ON at 20:25 with no entry saved. By Google's own description what a person asks Gemini to remember is saved there and used in every chat, which on a shared account crosses users. Turned off on 2026-10-01 at 21:08 with the owner's permission ("Cho tắt"), that switch only, no dialog; read back `false` after a fresh load. A leak test with it on (a word told in one conversation, asked in a new one) had come back "Unknown". **Since e64575a (2026-10-02) the driver reads this switch too before every turn**, on its own page and after personal context, in one tab, and refuses while it is on (`provider_misconfigured`, "the shared Gemini account has saved info switched on ..."); health's `memory` says `off` only when both switches read off. On the real profile the look takes 2.9 to 4.5s for both pages. **On 2026-10-02 at 01:26 the agent turned the switch on for about 10 seconds with the owner's yes ("Cho làm"), the host worker stopped, to see the driver refuse on the real page (it did, in 2.9s), and off again: a fresh load read `false`, and the driver's next look read `off`** |
| Gemini, connected apps (`gemini.google.com/apps`) | Google Workspace OFF | Read 2026-10-01 20:58, nothing changed. Off: Google Workspace, Search services, Google Photos, Contacts, YouTube Music, a second YouTube entry and 13 third-party apps. On: YouTube, Gemini Notebook, Google Flights, Google Hotels, Verify AI. Gemini Notebook lets Gemini use the account's own notebooks, if it has any: told to the owner, left as it is |
| Gemini, activity retention (`myactivity.google.com/product/gemini`) | ON, deliberately | Reads "Đang bật". It is NOT the leak switch and must stay on: the page says that with it off Google keeps conversations for 72 hours only, which would break one thread per conversation. Turning off the wrong one of the two is the trap here |

Turned off on 2026-09-23 and verified: a fact stated in one conversation returned "Unknown" in a
new one, while the same thread still recalled it. Ask the same question of any provider added
later, before more than one person uses it.

Since 983e542 the worker reads the switch before every turn (`GET /backend-api/settings/user`,
`settings.m3m`) and refuses to send while it is on; the job fails as `provider_misconfigured` and
refunds. `curl -s localhost:8000/health | python3 -m json.tool | grep memory` shows the last
reading: off, on, unknown, or null before the first turn.

## Local ports

| What | Port | Where it runs |
|------|------|---------------|
| API | 3000 | Docker |
| Web | 5173 | Docker |
| Worker | 8000 | Host, needs the cloakbrowser venv |

## Quick checks

```bash
# Docker up
docker info > /dev/null 2>&1 && echo "Docker OK" || echo "Docker not running"

# Provider session saved
ls -d storage/sessions/*/ 2>/dev/null || echo "No provider is logged in"

# Stack alive
curl -s localhost:3000/health; curl -s localhost:5173/ -o /dev/null -w " web %{http_code}\n"
curl -s localhost:8000/health

# Who spent what (admin token: the first registered account), plus threads still to remove
curl -s -H "Authorization: Bearer $TOKEN" localhost:3000/admin/usage | python3 -m json.tool

# The invite code needed to register lives in .env; read it yourself, it is a secret
grep INVITE_CODE .env
```
