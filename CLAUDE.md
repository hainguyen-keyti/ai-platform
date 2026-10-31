# AI Platform

Multi-model browser automation platform (ChatGPT, Grok, Gemini) with chat, image generation, and
video script generation. MVP for team, SaaS-ready architecture.

State and context live in `docs/agent/`. AT THE START OF EVERY SESSION: read `docs/agent/PROJECT.md`
and `docs/agent/HANDOFF.md` before doing anything, restate them for the user to confirm, then start
(or the user types /kt:load). AT THE END OF THE SESSION: update `docs/agent/HANDOFF.md` (or the user
types /kt:save).

## Standard commands

Setting up a new machine (`.env`, the venv, node, Docker, on Windows WSL and its fonts): `README.md`.
On Windows every command below runs inside WSL, from the project folder.

```
Install: docker compose build
Run (the providers in .env's PROVIDERS, chatgpt,grok,gemini): docker compose up -d && ./scripts/run-worker.sh
Stop: docker compose down
The real worker as a service (installed once, README step 10): systemctl --user start|stop|restart|status aip-worker
Log in a provider: ~/cloakbrowser-env/bin/python scripts/login_provider.py <chatgpt|grok|gemini>
Quick gate: python3 acceptance.py
Full gate: ./scripts/full-gate.sh
Provider smoke: python3 acceptance.py --real --keep --provider <chatgpt|grok|gemini>
Real journey: INVITE_CODE=... ~/cloakbrowser-env/bin/python tests/ui_journey.py
Site probe: ~/cloakbrowser-env/bin/python tests/provider_probe.py all
MCP server test (its own venv, README step 11): ~/.venvs/aip-mcp/bin/python tests/test_mcp_chatgpt_images.py
MCP stress (its own temp stack with a mock worker, about 3 minutes, in no gate): ~/.venvs/aip-mcp/bin/python tests/stress_mcp.py
Owner's cleanup (dry run; --yes deletes, owner only): ~/cloakbrowser-env/bin/python scripts/purge_test_residue.py <list.json>
```

The full gate is the quick gate, `npm run build` in `web/`, then `tests/ui_smoke.py` against a
compose stack and a mock worker of the gate's own (project `aip-gate`, api :3100, web :5273,
worker :8100, database in `storage/gate/`), so it never touches the real stack or its jobs and
the real worker can keep running. The gates mock the provider boundary on purpose so they can be rerun freely. `--real` drives
the actual browser session of the provider `--provider` names (chatgpt by default): it takes minutes
and spends account quota, so run it when the browser flow itself changed, not on every commit. The
real journey walks the web interface as a user with the host worker in real mode (two turns, one
picture). The site probe re-measures what the worker
relies on (turn requests, memory switch, error banner, DOM fallback, thread deletion) and cleans
up its own thread; `memory-toggle` only by name, with the worker stopped.

`tests/ui_smoke.py` and `tests/ui_journey.py` import cloakbrowser, so they run under the venv
python. ui_smoke needs a running stack, INVITE_CODE, and a worker started with
`PROVIDER_MODE=mock MOCK_DELAY_SECONDS=4`. The delay is what makes the waiting state observable;
without it the typing indicator check cannot see anything and fails.

## Allowed / Ask first / Forbidden

**Allowed:** read/write code, run docker, create files, run scripts, push `master` to the private
`origin` once a plan has closed with its full gate green (the owner's standing yes, 2026-10-02)

**Ask first:** any other push (another remote, a gate that is red or was not run, a force push),
delete data, change provider credentials, add new providers

**Forbidden:** commit secrets to git, delete browser sessions while in use, expose credentials in logs

## Working rules

The shared working rules (scope, tests, verification, parked questions, git) are injected by the kt
plugin at the start of every session in the `=== kt rules ===` block; this file only keeps the rules
SPECIFIC to this repo, and a repo rule wins on conflict.

- All providers use cloakbrowser, not API: browser sessions are the source of truth for auth state.
- Media files live on local disk (`storage/media`); Cloudflare R2 is deferred (DECISIONS section 3).
- One browser session per account at a time: a session is the profile `storage/sessions/<provider>/` or
  `<provider>-<name>/` with its own device seed, made only by the login script, and Chromium opens it for
  one browser at a time. Take an account off the host worker before a gate, a probe or a login uses it;
  never copy a profile, never delete its `device-seed` alone.
- A provider thread belongs to the account that made it: a conversation is pinned to its account from its
  first claim (`conversations.account`), and only that account's runner may take its jobs or delete its
  thread. A new provider is a `BaseProvider` taking `account` and a line in `build_provider`.
- Name a failure's cause only from the failing run's own record: run real gates with `--keep` and
  read the worker's error (the api's `thread_tombstones.error`, the job's error) before fixing; a
  defect measured elsewhere is a suspect until that record names it (paid for twice, 2026-09-27).

## Agent skills

### Issue tracker

Issues live in GitHub Issues on hainguyen-keyti/ai-platform (via `gh`). See `docs/agents/issue-tracker.md`.

### Triage labels

The five default triage labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Precedence over the kt layer

Where a mattpocock skill and the kt layer (`docs/agent/`, the `=== kt rules ===` block, the
session-start hook) disagree, the mattpocock skill wins (the owner, 2026-10-27). It does not widen
the Allowed / Ask first / Forbidden list above: a push still follows it, and creating or changing a
GitHub issue, comment or label is still asked first.

Three overlaps, settled:
- **Specs**: a new spec goes to a GitHub issue through `to-spec`; `docs/specs/` keeps the existing
  ones and takes no new ones.
- **Handoff between sessions**: kt's `docs/agent/HANDOFF.md` (`/kt:load`, `/kt:save`);
  `/mattpocock-skills:handoff` only when work moves to another folder, such as a prototype.
- **Commits**: `implement` commits locally on its own; a push still follows the rule above.
