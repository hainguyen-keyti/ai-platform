"""A provider's session: one browser profile on disk, opened as one device.

Measured 2026-10-01: every cloakbrowser launch draws a random fingerprint seed (three launches read
the GPU as M1, M4 Pro, M1), so a state file saved at login and loaded again by the worker, a gate or
a probe reached the site from another device each time, and nothing a browser learned was written
back. Two fresh logins were ended by their sites within the hour. A profile keeps what its browser
learns, Chromium lets one browser at a time open it, and the seed kept inside it makes every launch
the same device.
"""

import random
from pathlib import Path

from src.providers.base import ProviderError

SEED_FILE = "device-seed"
NO_SESSION = "no saved session at {}; run scripts/login_provider.py {}"


def profile_of(sessions_path, name: str) -> Path:
    return Path(sessions_path) / name


def device_seed(profile: Path) -> int:
    """The profile's own seed, drawn the first time and kept beside its cookies."""
    kept = profile / SEED_FILE
    if not kept.exists():
        kept.write_text(str(random.randint(10000, 99999)))
    return int(kept.read_text().strip())


def open_session(sessions_path, name: str, headless: bool = True, create: bool = False):
    """The provider's browser on its own profile, the same device as at its login.

    Only the login script creates a profile. A profile that another browser has open is refused by
    Chromium itself; that is said in words, never answered with a session that is not this one.
    """
    import cloakbrowser

    profile = profile_of(sessions_path, name)
    if create:
        profile.mkdir(parents=True, exist_ok=True)
    elif not profile.is_dir():
        raise ProviderError(NO_SESSION.format(profile, name))
    try:
        return cloakbrowser.launch_persistent_context(
            str(profile), headless=headless, args=["--fingerprint={}".format(device_seed(profile))])
    except Exception as exc:
        if "ProcessSingleton" not in str(exc):
            raise
        raise ProviderError("the {} session is open in another browser (a worker, a gate, a probe "
                            "or the login script); stop that one first".format(name)) from exc
