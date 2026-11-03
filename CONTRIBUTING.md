# Contributing

Issues and pull requests are welcome. Follow [`README.md`](README.md) to get a working setup.

## Before you open a pull request

- Run the full gate and say the result: `./scripts/full-gate.sh`. It mocks the providers and uses a
  stack of its own, so it spends no account's quota and can be rerun freely.
- Add a test that fails without your change. Most live in `tests/`, and the quick gate
  (`python3 acceptance.py`) runs the suites it lists.
- Change one thing at a time, and write code that reads like the code around it.

## Changes to a provider's driver

The sites change without notice, so a driver is built on what a site was measured to do. Say what you
measured and when. A real run spends your own account's quota and can draw the site's bot check, so
keep such runs few and never put them in a gate:

```bash
~/cloakbrowser-env/bin/python tests/provider_probe.py all
python3 acceptance.py --real --keep --provider <chatgpt|grok|gemini>
```

## Never commit

`.env`, anything from `storage/` (the database, the media and the logged-in browser profiles), or a
page or log holding a real account's name, thread or token. Check a captured page before adding it
to `tests/fixtures/`.
