# AI Platform

A web app for a team to chat, make pictures and write video scripts with ChatGPT, Grok and Gemini,
driven through real logged-in browser sessions (cloakbrowser), not provider APIs. What it is, how it
is built and where it stands: [`docs/agent/PROJECT.md`](docs/agent/PROJECT.md).

Three parts: the **api** (FastAPI, Docker, port 3000), the **web** (React and Vite, Docker, port
5173), and the **worker** (Python and cloakbrowser, on the host, port 8000), which asks the api for
jobs with `WORKER_TOKEN` and drives the browsers.

These steps take a fresh clone to a green full gate on Windows 11 with WSL2 (Ubuntu 26.04), where
they were walked. On macOS, where the project ran before, skip the Windows-only steps; this README
has not been walked there.

## 1. Prerequisites

- **Windows: everything below runs inside WSL** (Ubuntu), in a WSL terminal, never in PowerShell or
  cmd: the scripts are `sh`, the worker and the gates need a Linux venv, and the paths are Linux
  paths. A clone on a Windows drive is reached as `/mnt/<drive>/...` (this machine:
  `/mnt/d/keyti/ai-platform`, where the full gate runs).
- **Windows: the three packages cloakbrowser's Chromium needs that a new WSL Ubuntu lacks**:
  `sudo apt update && sudo apt install -y libnss3 libnspr4 libasound2t64` (the names on Ubuntu
  26.04). Without them the browser does not start, and the gates' browser checks fail. `ldd ~/.cloakbrowser/chromium-*/chrome | grep "not found"` prints nothing
  once the browser is downloaded and every library is there.
- git.
- [uv](https://docs.astral.sh/uv/getting-started/installation/), which also installs Python 3.11:
  `curl -LsSf https://astral.sh/uv/install.sh | sh`, then open a new shell so `~/.local/bin`, where
  it puts `uv`, is on PATH.
- `python3` on PATH: the quick gate, `acceptance.py`, uses only the standard library and runs under
  any python3 (Ubuntu and macOS ship one). WSL's Ubuntu has no `python` command, so the commands
  here say `python3`.
- Node.js 22 or newer with npm (the web image uses `node:22-alpine`): the full gate builds the web
  on the host. This machine's WSL runs 24.22.1, the linux-x64 archive from nodejs.org unpacked into
  `~/.local/opt` with `node`, `npm` and `npx` linked into `~/.local/bin`.
- Docker with compose v2. macOS: Docker Desktop. Windows: Docker Desktop with the WSL2 backend and
  **Settings > Resources > WSL Integration turned on for the distro** you work in, so `docker` and
  `docker compose` work inside WSL. Docker Desktop on Windows does not start by itself: start it
  before the stack.

## 2. Clone

```bash
git clone <repo-url> ai-platform
cd ai-platform
```

`.gitattributes` checks every text file out with LF (`* text=auto eol=lf`), whatever
`core.autocrlf` says: a CR breaks the shell scripts and the `.env` that `run-worker.sh` sources. On
Windows, check it, above all if the clone was made by Windows git:

```bash
git ls-files --eol scripts/ .env.example
```

Every row must show `w/lf`. A `w/crlf` means the files were checked out before `.gitattributes`
existed; write them again from the index with `git rm --cached -r -q . && git reset --hard` (this
discards uncommitted changes).

## 3. `.env`

```bash
cp .env.example .env
```

Replace the three `change-me` values, `JWT_SECRET`, `INVITE_CODE` and `WORKER_TOKEN`, each with a
new random string, for example the output of `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
Every other line is the value a real run uses; `.env.example` explains each one. `.env` is
git-ignored; never commit it. `INVITE_CODE` is what people type to register, and the full gate reads
it from this file.

Compose reads `.env` for the api (it refuses to start without the three secrets), and
`scripts/run-worker.sh` exports every line of it to the worker. A name given on the command line, or
already exported by the shell, wins over the file, even an empty one.

## 4. The worker's venv

The worker, the gates and the scripts run under one venv, `~/cloakbrowser-env` by default:

```bash
uv venv --seed --python 3.11 ~/cloakbrowser-env
~/cloakbrowser-env/bin/pip install -r worker/requirements.txt -r api/requirements.txt
```

- `--seed` puts pip in the venv: `run-worker.sh` and `acceptance.py` call the venv's pip.
- `worker/requirements.txt` pins `cloakbrowser==0.5.10` and `playwright==1.63.0` (a new
  cloakbrowser can bring a new Chromium build, which changes what the sites see); install those
  pins, not newer versions.
- `api/requirements.txt` is needed too: `acceptance.py` starts its own api under this venv.
- A venv elsewhere: set `CLOAKBROWSER_VENV` to its path. `scripts/run-worker.sh`,
  `scripts/full-gate.sh` and `acceptance.py` read it; the other scripts are run as
  `<venv>/bin/python <script>`.
- The first cloakbrowser launch downloads its Chromium into `~/.cloakbrowser`. If the first quick
  gate times out on a browser check while that runs, run it again.

## 5. Windows only: the Windows fonts in WSL

cloakbrowser's Chromium presents itself as Windows (`navigator.platform` is `Win32`). In a bare WSL
it rendered every Linux family it was given (Roboto, Ubuntu, even DejaVu Serif) as DejaVu Sans,
which is wider, and `tests/ui_smoke.py` reads 73/74 (the Vietnamese phone nav takes two rows at
360px). With the Windows fonts below, the web renders in Arial and ui_smoke reads 74/74. Copy the Windows fonts into WSL and refresh the
cache (`fc-cache` is the `fontconfig` package):

```bash
mkdir -p ~/.local/share/fonts/windows
cd /mnt/c/Windows/Fonts
cp arial.ttf arialbd.ttf arialbi.ttf ariali.ttf \
   calibri.ttf calibrib.ttf calibrii.ttf calibril.ttf calibrili.ttf calibriz.ttf \
   consola.ttf consolab.ttf consolai.ttf consolaz.ttf \
   cour.ttf courbd.ttf courbi.ttf couri.ttf framd.ttf framdit.ttf marlett.ttf msgothic.ttc \
   segoeui.ttf segoeuib.ttf segoeuii.ttf segoeuil.ttf segoeuisl.ttf segoeuiz.ttf \
   ~/.local/share/fonts/windows/
cd -
fc-cache -f
fc-list | grep -i segoe
```

The last line must list Segoe UI. macOS needs no step here.

## 6. The web's packages

```bash
(cd web && npm ci)
```

The full gate runs `npm run build` on the host, so the host needs its own `web/node_modules`. The
web container keeps a separate one in an anonymous volume. npm 11 warns that it held esbuild's
postinstall script; the build works without it.

## 7. Docker

```bash
docker compose build
docker compose up -d
```

The api answers on http://localhost:3000/health and the web on http://localhost:5173.

**Register your own account now**, at http://localhost:5173 with the invite code, before the full
gate: the first account on an empty database is the admin, and the full gate's `tests/ui_smoke.py`
registers its test accounts in this same database (`storage/db`). Run the gate first and its test
account is the admin.

## 8. The gates

Quick gate, about 5 minutes, its own ports, temp database and mock providers, safe to rerun:

```bash
python3 acceptance.py
```

It prints a PASS/FAIL table and exits non-zero on a failure.

Full gate, about 8 minutes, in one command:

```bash
./scripts/full-gate.sh
```

It runs, stopping at the first red step: the quick gate; `npm run build` in `web/`;
`docker compose up -d` and a wait for the api and the web; a mock worker on :8000 with
`MOCK_DELAY_SECONDS=4` when nothing answers there (its log in `~/.cache/ai-platform/`, stopped on
exit; a worker already on :8000 is used only if its health says mock mode); then
`tests/ui_smoke.py` with `INVITE_CODE` read from `.env`. It needs the venv, `.env` and Docker
running, and ports 3000, 5173 and 8000 for the stack and the worker.

### `.claude/test-command.txt`

Agent sessions run the full gate through the one line in `.claude/test-command.txt`. The file names
this machine's path, so it is git-ignored and each machine writes its own. On Windows the line runs
the gate inside WSL from the Windows side (this machine runs it as `cmd.exe /d /c "<line> 2>&1"`
from the project folder); change the distro name and the path to yours:

```
wsl -d Ubuntu --exec bash -lc "cd /mnt/d/keyti/ai-platform && ./scripts/full-gate.sh"
```

Double quotes: cmd.exe and wsl.exe do not treat single quotes as quotes. On macOS the line would be
`cd /path/to/ai-platform && ./scripts/full-gate.sh` (not tried there yet).

## 9. Logging in a provider

Each provider the worker serves (`PROVIDERS` in `.env`, `chatgpt,grok,gemini`) needs a logged-in
session, the browser profile `storage/sessions/<provider>/`, made only by the login script:

```bash
~/cloakbrowser-env/bin/python scripts/login_provider.py chatgpt
```

(or `grok`, `gemini`). A browser window opens on the provider's site; log in by hand, and the
script closes it once the login is real. On Windows the window has to show through WSLg (WSL's
own display); no login has been tried from WSL yet. A profile opens in one browser at a
time, so stop the worker, or take that provider off it, first. Never copy a profile between
machines, and never delete its `device-seed` alone. `storage/` is git-ignored: a new machine logs
in again.

## 10. Running it

```bash
docker compose up -d
./scripts/run-worker.sh
```

The worker serves the providers in `PROVIDERS`, in real mode (`PROVIDER_MODE=mock` for canned
replies). Open http://localhost:5173 and sign in (step 7). Stop with `docker compose down` and
Ctrl-C on the worker.

## Troubleshooting

- **The api logs `Could not import module "src.main"`** (or the full gate stops at
  `full-gate: api does not answer on :3000`) after Windows, WSL or Docker Desktop restarts: Docker
  Desktop started the container before WSL had mounted the project's drive, so the api's bind
  mount is empty. Start Docker Desktop, then from the project folder in WSL:
  `docker compose up -d --force-recreate`. The database is on the `storage/db` bind mount and
  survives.
- **After a change to `web/package.json` or `web/package-lock.json`**: the web image installs with
  `npm ci`, but the container keeps its old `node_modules` volume on a plain `up -d`. Run
  `docker compose build web && docker compose up -d --renew-anon-volumes web`.
- **The web and the api are silent while :8000 still answers**: the host worker does not depend on
  Docker, so this is the stack, not the platform; check that Docker Desktop is running, then the
  first item above.

More traps, and the project's live state: `docs/agent/HANDOFF.md`. Working rules for agents:
`CLAUDE.md`.
