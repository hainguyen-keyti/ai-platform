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

**Register your own account now**, at http://localhost:5173 with the invite code: the first account
on an empty database is the admin. The full gate's test accounts live in a database of its own
(`storage/gate/`, below), never in `storage/db`.

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

It runs, stopping at the first red step: the quick gate; `npm run build` in `web/`; **a stack of
its own**, a second compose project `aip-gate` (api :3100, web :5273, its database and media in
`storage/gate/`, emptied each run); a mock worker of its own on :8100 with `MOCK_DELAY_SECONDS=4`,
serving that api only (its log in `~/.cache/ai-platform/`); then `tests/ui_smoke.py` with
`INVITE_CODE` read from `.env`. It takes its stack down and stops its worker on exit. The real
stack, its database and a real worker are never touched, so the gate can run while people use the
platform. It needs the venv, `.env` and Docker running, and ports 3100, 5273 and 8100 free
(`GATE_API_PORT`, `GATE_WEB_PORT`, `WORKER_PORT` change them).

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

To keep the real worker up without a terminal open, make it a service of WSL's systemd:

```bash
./scripts/install-worker-service.sh 8010 chatgpt,grok
systemctl --user start aip-worker
```

Port and providers are optional (8000 and `.env`'s `PROVIDERS`). It comes back after a crash and when
WSL starts, and logs to `~/.cache/ai-platform/host-worker-real.log`. Before a login or a probe that
needs the session, `systemctl --user stop aip-worker`. Code changes reach it with
`systemctl --user restart aip-worker`.

The picture budget's count is kept in `storage/pacing-<provider>.json`, so a restart does not give it
back.

## 11. MCP server for ChatGPT pictures

`mcp_server/chatgpt_images.py` lets an agent (Claude Code, Claude Desktop, any MCP client) make
pictures with ChatGPT on this platform as a tool. Its host starts it as a subprocess over stdio; it
calls the platform's image API (`docs/api-v1-images.md`) with your own API key. Two tools:

- `generate_image(prompt, reference_path=None, save_dir=None, wait_seconds=420, preview=True)`:
  sends the prompt (and a PNG, JPEG or WEBP reference picture, if given), waits for ChatGPT (about a
  minute), saves every picture it made and answers with the files' paths. A request still running
  when the wait ends answers with its id. Every request of one key goes into that key's own
  ChatGPT thread for the day (UTC). `continue_from=<request id>` changes a picture already made
  ("the same, at night"): the prompt goes into the ChatGPT thread that made it, so the picture is
  not sent back. `reference_paths=[…]` sends up to 4 reference pictures in order ("the character of
  the first in the scene of the second"), all together under 10 MB.
- `generate_images(prompts, reference_path=None, save_dir=None, wait_seconds=1800, preview=True)`:
  a set of 1 to 20 prompts, sent at once, made one after another (ChatGPT makes one picture at a
  time), with the same reference picture for each when one is given. It reports "k of n done" as
  it goes and answers each prompt's files, failure reason, or request id if it is still running. A
  refusal when sending (no credit left, say) stops sending the rest, and the answer says which
  prompts were not sent.
- `get_image(request_id, save_dir=None, preview=True)`: collects such a request later.
- `account_status()`: the credits left today, when they come back, whether ChatGPT is served right
  now, and how much of the worker's picture budget is used (40 in three hours by default,
  `IMAGE_BUDGET_3H`; past it requests wait in the queue); worth asking before a set.
- `cancel_image(request_id)`: cancels a request sent by mistake, queued or running, and gives its
  credit back.

Every answer carries a preview of each picture (a JPEG, at most 512 px a side) for the agent to look
at, and the same facts as structured content (the request, its status, each file). `preview=False`
leaves the preview out. A picture is saved as `<prompt slug>-<request>-<n>.png`, for example
`meo-cam-ben-cua-so-b5f940d8-1.png`, and a `.json` of the same name beside it records the prompt,
the request, the reference picture and the times.

Each request costs one credit, as on the web, and a failed one gives it back. Pictures go to
`save_dir`, or `AIP_SAVE_DIR`, or `<temp>/aip-pictures`. Under WSL a Windows path you give
(`D:\...`) is read as `/mnt/d/...`, and every saved file is also named by its Windows path
(`\\wsl.localhost\...`).

Each day at `LIBRARY_CLEANUP_AT` (HH:MM in UTC, 16:30 by default, which is 23:30 in Vietnam; empty
turns it off) the worker moves to ChatGPT's Library trash the pictures from before today of the
platform's own threads, a page at a time while it has no job. A trashed file can be restored from
the Library and no longer counts in the store. Nothing else on the account is touched: not a file of
another thread, not a file that is not a picture. Worker health shows the last run as
`library_cleanup` and the store as `storage`. A `continue_from` on a request from before today still
worked after its picture was trashed (measured once, 2026-10-30).

Install it in a venv of its own (the `mcp` SDK and Pillow for the previews, pinned in its
requirements):

```bash
uv venv --python 3.11 ~/.venvs/aip-mcp
VIRTUAL_ENV=~/.venvs/aip-mcp uv pip install -r mcp_server/requirements.txt
```

Make a key on the web's **API** page (step 7's account), then register the server. The key goes in
the server's environment, never on its command line:

- **Claude Code on Windows, the server in WSL** (this machine): Windows variables reach WSL only when
  `WSLENV` names them (`/u`: when WSL is started from Windows). From PowerShell:

  ```
  claude mcp add --env AIP_API_KEY=aip_... AIP_API_URL=http://localhost:3000 WSLENV=AIP_API_KEY/u:AIP_API_URL/u --transport stdio aip-chatgpt-images -- wsl -d Ubuntu --exec /home/<you>/.venvs/aip-mcp/bin/python /mnt/d/keyti/ai-platform/mcp_server/chatgpt_images.py
  ```

- **Claude Code on Linux or macOS** (or inside WSL):

  ```bash
  claude mcp add --env AIP_API_KEY=aip_... --transport stdio aip-chatgpt-images -- ~/.venvs/aip-mcp/bin/python "$PWD/mcp_server/chatgpt_images.py"
  ```

- **Claude Desktop**: in `claude_desktop_config.json`, under `mcpServers`:

  ```json
  "aip-chatgpt-images": {
    "type": "stdio",
    "command": "/home/<you>/.venvs/aip-mcp/bin/python",
    "args": ["/path/to/ai-platform/mcp_server/chatgpt_images.py"],
    "env": {"AIP_API_KEY": "aip_...", "AIP_API_URL": "http://localhost:3000"}
  }
  ```

  (on Windows, `"command": "wsl"` with the WSL line's arguments and its `WSLENV` in `env`).

In Claude Code, `/mcp` shows whether it connected. Then ask the agent for a picture, or for a set:
"make these five pictures with ChatGPT and save them in `D:\pictures\fox`: …". A call still running
after two minutes moves to a background task in Claude Code, and its answer arrives when it ends.
Its own test:
`~/.venvs/aip-mcp/bin/python tests/test_mcp_chatgpt_images.py` (a fake `/v1`, no account).

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
