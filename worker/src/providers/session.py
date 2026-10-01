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
SEEDS = (10000, 99999)
NO_SESSION = "no saved session at {}; run scripts/login_provider.py {}"
BAD_SEED = ("the device seed kept in {} cannot be read, so this profile's device is unknown; move the "
            "profile away and run scripts/login_provider.py {}")


def profile_of(sessions_path, name: str) -> Path:
    return Path(sessions_path) / name


def saved(sessions_path, name: str) -> bool:
    """Whether a login has made this provider's profile: the directory and the seed drawn for it."""
    profile = profile_of(sessions_path, name)
    return profile.is_dir() and (profile / SEED_FILE).is_file()


def device_seed(profile: Path, draw: bool = False) -> int:
    """The profile's own seed, kept beside its cookies.

    Only a login draws one, once, and only into a profile no browser has used: a used profile whose
    seed is gone holds a session made as a device nobody can name any more.
    """
    kept = profile / SEED_FILE
    if draw and not kept.exists() and not any(entry.name != ".DS_Store" for entry in profile.iterdir()):
        try:
            with open(kept, "x") as fresh:
                fresh.write(str(random.randint(*SEEDS)))
        except FileExistsError:
            pass
    try:
        text = kept.read_text().strip()
    except (OSError, ValueError):
        text = ""
    if not (text.isascii() and text.isdigit()) or not SEEDS[0] <= int(text) <= SEEDS[1]:
        raise ProviderError(BAD_SEED.format(kept, profile.name))
    return int(text)


def open_session(sessions_path, name: str, headless: bool = True, create: bool = False):
    """The provider's browser on its own profile, the same device as at its login.

    Only the login script creates a profile and draws its seed. A profile that another browser has
    open is refused by Chromium itself; that is said in words, never answered with a session that is
    not this one.
    """
    import cloakbrowser

    profile = profile_of(sessions_path, name)
    if create:
        profile.mkdir(parents=True, exist_ok=True)
    elif not saved(sessions_path, name):
        raise ProviderError(NO_SESSION.format(profile, name))
    seed = device_seed(profile, draw=create)
    try:
        return cloakbrowser.launch_persistent_context(
            str(profile), headless=headless, args=["--fingerprint={}".format(seed)])
    except Exception as exc:
        if "ProcessSingleton" not in str(exc):
            raise
        raise ProviderError("the {} session is open in another browser (a worker, a gate, a probe "
                            "or the login script); stop that one first".format(name)) from exc
