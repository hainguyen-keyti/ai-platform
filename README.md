# AI Platform

A self-hosted platform to chat, make pictures and write video scripts with ChatGPT, Grok and Gemini.
It drives your own logged-in browser sessions instead of provider APIs, and gives you three ways in:
a web app, an HTTP API and an MCP server for AI agents.

> [!WARNING]
> **Read this before you use it.**
>
> - This project automates consumer accounts through a stealth browser. That may break the terms of
>   the services it drives, and an account can be limited or closed. Use your own accounts, at your
>   own risk, and check each service's terms yourself.
> - It is not affiliated with OpenAI, xAI or Google, and it comes with no warranty.
> - The MIT license covers this repository only. The first run downloads CloakBrowser's Chromium,
>   which has [a license of its own](https://github.com/CloakHQ/CloakBrowser/blob/main/BINARY-LICENSE.md):
>   it may not be redistributed, and offering it to third parties as a service needs a separate
>   agreement with its vendor.
> - Sites change without notice, and a change can break a driver until someone updates it.

## Contents

- [What you get](#what-you-get)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Install](#install)
- [Use it](#use-it): [web](#the-web-app), [HTTP API](#the-http-api), [MCP server](#the-mcp-server)
- [Video script presets](#video-script-presets)
- [Run it day to day](#run-it-day-to-day)
- [Configuration](#configuration)
- [Development and tests](#development-and-tests)
- [Troubleshooting](#troubleshooting)

## What you get

- **Chat and pictures** with ChatGPT, Grok and Gemini, from one interface.
- **Video scripts**, written by a chat model and checked before you get them. A script can target
  Google Flow, MiniMax H3 or Wan 2.2, or be a director's whole film: concept, screenplay, timed shots
  and post-production, for whatever tool makes it.
- **Several users**, invite-only, each with a daily credit balance. A failed job gives its credit back.
- **Several accounts per provider**, so that requests go to one with room.
- **Pacing built in**: a gap between turns, a picture budget and a back-off after errors, per account.

## How it works

```
 Web app (React)        Your program        AI agent
   :5173                     |            MCP server (stdio)
      |                      |                   |
      +----------------------+-------------------+
                             v
                   API (FastAPI) :3000 ------ SQLite, media on disk
                             ^
                             |  the worker asks for jobs and posts results
                             |
                   Worker (Python) on the host
                             |
                   One browser per logged-in account
                             |
                   ChatGPT / Grok / Gemini
```

The API and the web run in Docker. The worker runs on the host, because it needs a real browser and
its logged-in profiles. The API never calls the worker: the worker asks for work, so it can restart
without losing the queue.

## Requirements

| What | Notes |
|---|---|
| Operating system | Windows 11 with WSL2 (Ubuntu) is the tested setup. macOS was used earlier, and native Linux should work, but neither has been walked through with this guide |
| Docker with Compose v2 | On Windows: Docker Desktop with the WSL2 backend, and **Settings > Resources > WSL Integration** on for your distro |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Installs Python 3.11 for the worker |
| `python3`, git | Any recent `python3` |
| A screen for the login step | The first login opens a browser window. WSLg shows it on Windows 11 |
| Provider accounts | Your own, for each provider you want to serve |

**On Windows, run everything below in a WSL terminal**, not in PowerShell or cmd. The scripts are `sh`
and the worker needs a Linux virtual environment.

Also on Windows and Ubuntu, install the libraries the browser needs (the names are for recent Ubuntu):

```bash
sudo apt update && sudo apt install -y libnss3 libnspr4 libasound2t64
```

## Install

### 1. Clone

```bash
git clone https://github.com/hainguyen-keyti/ai-platform.git
cd ai-platform
```

On Windows, check that the files came out with LF line endings, or the scripts will not run:

```bash
git ls-files --eol scripts/ .env.example
```

Every row must show `w/lf`.

### 2. Create `.env`

```bash
cp .env.example .env
```

Replace the three secrets `JWT_SECRET`, `INVITE_CODE` and `WORKER_TOKEN`, each with its own random
value. This prints one:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

`INVITE_CODE` is what people type to register. Never commit `.env`; it is already git-ignored. The API
refuses to start without these three values. All the other settings have working defaults:
see [Configuration](#configuration).

### 3. Create the worker's virtual environment

```bash
uv venv --seed --python 3.11 ~/cloakbrowser-env
~/cloakbrowser-env/bin/pip install -r worker/requirements.txt -r api/requirements.txt
```

Keep the pinned versions: a new CloakBrowser can bring a new Chromium build, which changes what the
sites see. The browser itself is downloaded to `~/.cloakbrowser` the first time it starts, so the first
run takes longer. To keep the environment elsewhere, set `CLOAKBROWSER_VENV` to its path.

### 4. Start the API and the web

```bash
docker compose build
docker compose up -d
```

Check that the API answers:

```bash
curl http://localhost:3000/health
```

It should print `{"status":"ok"}`.

### 5. Create your account

Open http://localhost:5173 and register with your invite code. **The first account on an empty database
becomes the admin**, so register yourself first.

### 6. Log in to each provider

The worker uses a browser profile for each account. Make one for each provider in `PROVIDERS`
(`chatgpt,grok,gemini` by default; remove the ones you do not want from `.env`):

```bash
~/cloakbrowser-env/bin/python scripts/login_provider.py chatgpt
~/cloakbrowser-env/bin/python scripts/login_provider.py grok
~/cloakbrowser-env/bin/python scripts/login_provider.py gemini
```

A browser window opens on the provider's site. Log in by hand. The script closes the window by itself
once the login is real. It never sees your password, but the session is saved in
`storage/sessions/<provider>/`, so **anyone who can read that folder is signed in as you**.

**Then turn the account's memory off** in that provider's own settings: ChatGPT's memory, Grok's memory,
and Gemini's personal context and saved info. Otherwise one person's chat could leak into another's, so
the worker refuses to send a turn to an account with memory on, and says why.

Rules for profiles:

- A profile opens in one browser at a time, so stop the worker before you log in.
- Never copy a profile to another machine: log in again there.
- Never delete the `device-seed` file alone.

### 7. Start the worker

```bash
./scripts/run-worker.sh
```

Leave it running. The API and the web now have real providers behind them.

### 8. Try it

Open http://localhost:5173, sign in, pick a provider and send a message. A chat answer usually takes
under a minute, and a picture about a minute.

No account handy, or just testing the setup? Run the worker with canned answers:

```bash
PROVIDER_MODE=mock ./scripts/run-worker.sh
```

## Use it

### The web app

Chat with any served provider, ask for a picture, attach files, and find everything in the gallery.
Each conversation stays with the provider and the account it started on. An admin can see each
account's state at `GET /admin/accounts`.

### The HTTP API

Create a key on the web's **API** page. It starts with `aip_` and is shown only once.

```bash
export AIP_API_KEY=aip_...

# Send a picture request: answers at once with an id
curl -X POST http://localhost:3000/v1/images \
  -H "Authorization: Bearer $AIP_API_KEY" \
  -F "prompt=a red fox in the snow"

# Ask for its status until it is done
curl -H "Authorization: Bearer $AIP_API_KEY" http://localhost:3000/v1/images/<id>
```

A ready-made client that needs only the standard library:

```bash
python3 scripts/image_api_example.py --prompt "a red fox in the snow" --out pictures
```

Every call, including video scripts, is described in [`docs/api-v1-images.md`](docs/api-v1-images.md).

### The MCP server

This lets an agent (Claude Code, Claude Desktop or any MCP client) use the platform as tools. It runs as
a subprocess of the agent's host and calls the API with your key.

**Install it** in its own environment:

```bash
uv venv --python 3.11 ~/.venvs/aip-mcp
VIRTUAL_ENV=~/.venvs/aip-mcp uv pip install -r mcp_server/requirements.txt
```

**Register it.** The key goes in the server's environment, never on its command line.

Claude Code on Linux or macOS, or inside WSL, from the repository folder:

```bash
claude mcp add --env AIP_API_KEY=aip_... --transport stdio aip-chatgpt-images -- ~/.venvs/aip-mcp/bin/python "$PWD/mcp_server/chatgpt_images.py"
```

Claude Code on Windows, with the server in WSL, from PowerShell:

```
claude mcp add --env AIP_API_KEY=aip_... AIP_API_URL=http://localhost:3000 WSLENV=AIP_API_KEY/u:AIP_API_URL/u --transport stdio aip-chatgpt-images -- wsl -d Ubuntu --exec /home/<you>/.venvs/aip-mcp/bin/python /mnt/<drive>/<path>/ai-platform/mcp_server/chatgpt_images.py
```

Claude Desktop, in `claude_desktop_config.json` under `mcpServers`:

```json
"aip-chatgpt-images": {
  "type": "stdio",
  "command": "/home/<you>/.venvs/aip-mcp/bin/python",
  "args": ["/path/to/ai-platform/mcp_server/chatgpt_images.py"],
  "env": {"AIP_API_KEY": "aip_...", "AIP_API_URL": "http://localhost:3000"}
}
```

In Claude Code, `/mcp` shows whether it connected. A session started before you change the server keeps
the old process: open a new session.

**The tools:**

| Tool | What it does |
|---|---|
| `generate_image` | Makes one picture, optionally from reference pictures, and saves it |
| `generate_images` | Makes a set of 1 to 20 pictures, one after another |
| `get_image` | Collects a picture request that is still running or already done |
| `cancel_image` | Cancels a request sent by mistake and gives its credit back |
| `write_video_script` | Writes a script for `flow`, `minimax_h3` or `wan`, or a whole film with `production` |
| `get_video_script` | Collects a script that is still running or already done |
| `list_script_targets` | Says what each target takes |
| `list_presets`, `generate` | List the ready recipes, and run one |
| `list_sessions` | Lists your named sessions |
| `account_status` | Says the credits left, the picture budget and the queue |

Then just ask the agent, for example: "make five pictures of a fox in different seasons and save them in
`~/pictures/fox`".

Good to know:

- **Keep a character apart with a session.** Requests of one key share one thread per day, so pictures
  drift toward one look. Pass `session="woman-a"` to give a character a thread of its own that lasts
  across days.
- **Change a picture with `continue_from`**, using its request id, instead of sending it back.
- **Each request costs one credit**, and a failed one gives it back.
- Files go to `save_dir`, or `AIP_SAVE_DIR`, or `<temp>/aip-pictures`. Scripts are saved as Markdown and JSON.

## Video script presets

A preset is a recipe: one TOML file in [`mcp_server/presets/`](mcp_server/presets). It fills your inputs
into a template and sends the result as a normal request. To add one, add a file: no code is needed.

| Preset | Makes | You must give |
|---|---|---|
| `director-ad` | A director's whole product ad | `product`, `audience`, `benefit` |
| `director-story` | A director's whole short story | `idea`, `characters` |
| `director-review` | A director's whole creator-style review | `product`, `audience`, `experience` |
| `director-explainer` | A director's whole explainer | `topic`, `points`, `audience` |
| `content-ad-flow`, `content-review-flow` | Clips for Google Flow: 4 clips, 32s | Same as above |
| `content-story-flow` | Clips for Google Flow: 6 clips, 48s | `idea`, `characters` |
| `content-explainer-flow` | Clips for Google Flow: 5 clips, 40s | `topic`, `points`, `audience` |
| `short-film-flow`, `short-film-minimax`, `short-film-wan` | Your story, passed on with no direction | `story` |
| `character-portrait`, `character-scene` | A picture of a character, kept in its own session | See `list_presets` |

Ask an agent, or call the tool directly:

```
generate(preset="director-ad", inputs={
  "product": "a moss-green 500 ml steel bottle with a one-hand lid",
  "audience": "young office workers",
  "benefit": "opens with one hand, so you do not stop what you are doing",
  "seconds": 30
})
```

The `director-*` presets also take `seconds` (45 by default) and answer with a whole film, written in the
request's language (Vietnamese unless you say otherwise): concept, characters, settings, scenes of timed
shots of any length, and post-production. Each shot has its size, angle, lens, movement, composition,
action, light, color, sound, cut, lines and on-screen text. They name no tool: how the film gets made is
up to whoever makes it. If an idea is too small for its length, the ending tends to drag, so choose a
shorter `seconds`.

**What is guaranteed.** The API checks a script's shape: every field present, the film's length within
15% of what you asked, and lines that fit their shot. A script that fails is refused and its credit
comes back. **What is not guaranteed.** A rule written in a preset, such as "invent no claims" or "no
danger on screen", is a request to the model. Quality varies between runs, so read what comes back
before you use it, above all for ads and reviews.

## Run it day to day

| Task | Command |
|---|---|
| Start | `docker compose up -d`, then `./scripts/run-worker.sh` |
| Stop | Ctrl-C on the worker, then `docker compose down` |
| Worker health | `curl http://localhost:8000/health` |
| Add a second account | `~/cloakbrowser-env/bin/python scripts/login_provider.py chatgpt --account a2`, turn its memory off, restart the worker |

**Keep the worker running without a terminal**, as a systemd user service. On WSL this needs
`systemd=true` in `/etc/wsl.conf`:

```bash
./scripts/install-worker-service.sh            # optional arguments: port, providers
systemctl --user start aip-worker
systemctl --user status aip-worker
```

Its log is `~/.cache/ai-platform/host-worker-real.log`. Stop it before you log in to an account.

**Several accounts.** An account with room takes the next request, and two accounts can run at once. A
conversation stays on the account that started it. The picture budget, the back-off and the Library
cleanup are per account.

**Nightly Library cleanup.** Once a day, at `LIBRARY_CLEANUP_AT`, the worker moves to ChatGPT's Library trash
the pictures from before today of the platform's own threads. Nothing else on the account is touched,
and a trashed file can be restored. Set `LIBRARY_CLEANUP_AT=` (empty) to turn it off.

**Use it from another machine.** The defaults assume one machine: `docker compose` publishes its ports on
every network interface with no TLS, and it runs the API with auto-reload. Before you expose it, read
[`SECURITY.md`](SECURITY.md), and set `VITE_API_URL` to the address browsers will reach the API on.

## Configuration

All settings live in `.env`, and [`.env.example`](.env.example) explains each one. A name set on the command
line wins over the file. The ones you are most likely to change:

| Setting | Default | What |
|---|---|---|
| `PROVIDERS` | `chatgpt,grok,gemini` | Which providers this worker serves |
| `PROVIDER_MODE` | `real` | `mock` gives canned answers and needs no account |
| `DEFAULT_QUOTA` | `500` | Each new user's credits a day |
| `IMAGE_BUDGET_3H` | `40` | Pictures per account in a rolling 3 hours; past it, requests wait |
| `IMAGE_TOTAL_3H` | `0` | The same cap across a provider's accounts (0 is no cap) |
| `MIN_GAP_SECONDS` | `3` | The pause between turns |
| `COOLDOWN_BASE_SECONDS`, `COOLDOWN_MAX_SECONDS` | `30`, `900` | The back-off after provider errors |
| `BROWSER_IDLE_SECONDS` | `1800` | Close a browser unused this long (0 keeps it open) |
| `LIBRARY_CLEANUP_AT` | `16:30` | Daily ChatGPT Library cleanup, in UTC; empty turns it off |
| `TOKEN_TTL_HOURS` | `24` | How long a web login lasts |

The pacing settings can be set per provider, for example `MIN_GAP_SECONDS__GROK=150`. These defaults are
this project's own choices, not published limits: providers do not announce theirs, and they change.

## Development and tests

The tests mock the providers, so you can rerun them freely. They spend no account's quota.

```bash
python3 acceptance.py          # quick gate, about 5 minutes
```

The full gate also builds the web and walks it in a browser, on a stack of its own (API on :3100, web on
:5273, worker on :8100, data in `storage/gate/`), so it never touches your real data:

```bash
(cd web && npm ci)             # first time only; needs Node.js 22 or newer
./scripts/full-gate.sh         # about 10 minutes
```

On Windows, one layout check in the web test needs Windows fonts in WSL, or it fails on the wider
default font:

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
```

Against your real accounts (these spend quota and can draw a bot check, so use them sparingly):

```bash
python3 acceptance.py --real --keep --provider chatgpt
~/cloakbrowser-env/bin/python tests/provider_probe.py all
```

The MCP server has its own tests:

```bash
~/.venvs/aip-mcp/bin/python tests/test_mcp_chatgpt_images.py
~/.venvs/aip-mcp/bin/python tests/stress_mcp.py
```

**Add a provider:** write a `BaseProvider` that takes `account`, add it to `build_provider` in
`worker/src/pool.py` and to `PROVIDERS` and `FEATURES` in `api/src/models.py`.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) before you open a pull request.

## Troubleshooting

**The API does not answer after a restart of Windows, WSL or Docker.** Docker Desktop may have started the
container before WSL mounted the drive. It also does not start by itself unless you set it to. Start it,
then:

```bash
docker compose up -d --force-recreate
```

**The browser does not start.** A system library is probably missing. This prints what is:

```bash
ldd ~/.cloakbrowser/chromium-*/chrome | grep "not found"
```

**The browser download fails, or asks for a license key.** CloakBrowser's terms and downloads change over
time. Check [its documentation](https://github.com/CloakHQ/CloakBrowser#readme) for the pinned version in
`worker/requirements.txt`.

**A job fails with `no_worker`.** No worker has served that provider or account lately. Check that the worker
is running and that the provider is in `PROVIDERS`.

**A turn is refused: logged out, or memory on.** Stop the worker, log in again or turn memory off (step 6), and
start it. The provider is held out for 10 minutes after such a failure (`PROVIDER_HOLD_SECONDS`).

**A provider shows a Cloudflare or "unusual traffic" check.** The worker does not solve these. Slow down, give
it time, and log in by hand if needed. If it keeps happening, take the provider out of `PROVIDERS` for a while.

**A request waits for a long time.** Its account may have spent its picture budget, or be in a back-off. `GET
/v1/providers` and the MCP's `account_status` show `budget_free_at` and the queue.

**The web still runs old packages after a change to `web/package*.json`:**

```bash
docker compose build web && docker compose up -d --renew-anon-volumes web
```

## Contributing, security, license

Contributions are welcome: see [`CONTRIBUTING.md`](CONTRIBUTING.md). Report a vulnerability privately, as
[`SECURITY.md`](SECURITY.md) says. Released under the [MIT License](LICENSE).
