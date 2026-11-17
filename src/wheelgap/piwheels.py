"""--piwheels: say when piwheels has a wheel for a Raspberry Pi gap.

Only a hint under --explain: piwheels builds don't come from PyPI, and piwheels may not have every release.
So it never changes a status, the summary or the exit code.

A wheel counts for a target when:
- it's of the checked version, in a release that isn't yanked;
- its filename is a valid wheel filename whose tags the target accepts (target.accepts()).
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import quote

from packaging.version import InvalidVersion, Version

from . import cache, pypi
from .check import wheel_tags
from .sources import Package
from .targets import Target

# One package's JSON on piwheels.org, with its releases and wheel files.
API = "https://www.piwheels.org/project"
INDEX = "https://www.piwheels.org/simple"
MAX_BYTES = 4 * 1024 * 1024
WORKERS = 3
TIMEOUT = 15.0
DEADLINE = 30.0
TOO_LARGE = cache.TOO_LARGE
TOO_LARGE_ANSWER = f"answer too large (over {MAX_BYTES // (1024 * 1024)} MB)"
FAILED = "no usable answer"
DROPPED = "not asked: piwheels.org couldn't be reached, or was too slow"

# wheelgap platform targets piwheels can build wheels for: Raspberry Pi 32-bit (armv7l) and 64-bit (aarch64).
PLATFORMS = {"linux-armv7l", "linux-aarch64"}


class Unreachable(Exception):
    """piwheels.org couldn't be reached (DNS, a refused or timed-out connection): the other lookups would fail too."""


def wanted(targets: Iterable[Target]) -> bool:
    """Whether any of these gap targets could match a piwheels build."""
    return any(t.platform in PLATFORMS for t in targets)


def _same_version(a: str, b: str) -> bool:
    try:
        return Version(a) == Version(b)
    except InvalidVersion:
        return a == b


def parse_wheels(data: object, version: str) -> list[str]:
    """The wheel filenames of `version`, from a piwheels.org package JSON answer."""
    if not isinstance(data, dict):
        raise ValueError("unexpected response")
    releases = data.get("releases")
    if not isinstance(releases, dict):
        raise ValueError("unexpected response")
    for rel_ver, rel in releases.items():
        if isinstance(rel_ver, str) and _same_version(rel_ver, version):
            if not isinstance(rel, dict) or rel.get("yanked"):
                return []
            files = rel.get("files")
            if not isinstance(files, dict):
                return []
            valid = []
            for filename, info in files.items():
                if not (isinstance(filename, str) and filename.endswith(".whl") and isinstance(info, dict)):
                    continue
                if not (
                    isinstance(info.get("file_url"), str)
                    and isinstance(info.get("builder_abi"), str)
                    and isinstance(info.get("platform"), str)
                ):
                    continue
                valid.append(filename)
            return valid
    return []


def fits(wheel: str, target: Target) -> bool:
    """Whether a wheel installs on the target's Python and platform."""
    if target.platform not in PLATFORMS:
        return False
    tags = wheel_tags([wheel])
    return bool(tags) and any(target.accepts(t) for t in tags)


def fetch(key: str, version: str) -> list[str] | str | None:
    """Ask piwheels.org: the wheel filenames of `version` ([] for no such package, version, or wheels),
    TOO_LARGE, or None for an answer that can't be used (403, 429, 5xx, too slow, damaged).
    Raises Unreachable when piwheels.org can't be reached."""
    try:
        data = pypi.fetch_json(f"{API}/{quote(key, safe='')}/json/", timeout=TIMEOUT, attempts=1, max_bytes=MAX_BYTES)
    except urllib.error.HTTPError as e:
        return [] if e.code == 404 else None  # only a 404 says there's no such package
    except pypi.ResponseTooLarge:
        return TOO_LARGE
    except urllib.error.URLError as e:
        raise Unreachable from e
    except Exception:
        return None
    try:
        return parse_wheels(data, version)
    except ValueError:
        return None


def look_up(key: str, version: str, read_cache: bool = False, write_cache: bool = False) -> list[str] | str | None:
    """fetch(), through the 24-hour cache. Answers (wheels, none, too large) are cached; failures aren't."""
    if read_cache and (cached := cache.load_piwheels(key, version)) is not None:
        return cached
    found = fetch(key, version)
    if found is not None and write_cache:
        cache.save_piwheels(key, version, found)
    return found


@dataclass
class Lookups:
    found: dict[tuple[str, str], list[str]]  # (name, version) -> wheel filenames
    unchecked: dict[str, str]  # name -> why it has no usable answer: TOO_LARGE, FAILED or DROPPED
    stopped: bool  # piwheels.org couldn't be reached, or deadline passed


def look_up_all(
    wanted: Iterable[tuple[str, str]], read_cache: bool = False, write_cache: bool = False, deadline: float = DEADLINE
) -> Lookups:
    """Look up each (name, version), at most WORKERS at a time. The first lookup that can't reach piwheels.org stops
    the rest, and so does the deadline. Workers are daemon threads, so a stalled request can't hold up the run's exit."""
    todo: deque[tuple[str, str]] = deque(dict.fromkeys(wanted))
    asked = list(todo)
    results: dict[tuple[str, str], list[str] | str | None] = {}
    lock = threading.Lock()
    finished, stop = threading.Event(), threading.Event()

    def worker() -> None:
        while not stop.is_set():
            with lock:
                if not todo:
                    return
                item = todo.popleft()
            try:
                result = look_up(*item, read_cache, write_cache)
            except Unreachable:
                stop.set()
                finished.set()
                return
            with lock:
                if not stop.is_set():
                    results[item] = result
                    if len(results) == len(asked):
                        finished.set()

    if asked:
        start = time.monotonic()
        for _ in range(min(WORKERS, len(asked))):
            threading.Thread(target=worker, daemon=True).start()
        finished.wait(max(0.0, deadline - (time.monotonic() - start)))
        stop.set()
    with lock:
        found = {item: r for item, r in results.items() if isinstance(r, list)}
        unchecked: dict[str, str] = {}
        for item in asked:
            if item not in found:
                result = results.get(item)
                unchecked.setdefault(
                    item[0], TOO_LARGE_ANSWER if result == TOO_LARGE else FAILED if item in results else DROPPED
                )
        return Lookups(found, unchecked, len(results) < len(asked))


@dataclass
class Hint:
    name: str  # canonical package name
    version: str  # checked version
    wheels: dict[Target, list[str]]  # gap target -> list of matching wheel filenames


def hint(pkg: Package, targets: Iterable[Target], found: dict[tuple[str, str], list[str]]) -> Hint | None:
    """The hint for a package's gap targets, or None when no wheel fits any of them. The caller checks that the
    package is PyPI's (origin.known_pypi)."""
    if not pkg.version or not (wheels := found.get((pkg.key, pkg.version))):
        return None
    matched = {}
    for t in targets:
        matching = [w for w in wheels if fits(w, t)]
        if matching:
            matched[t] = matching
    return Hint(pkg.key, pkg.version, matched) if matched else None


def hint_text(pkg: Package, h: Hint, multi_py: bool) -> str:
    """piwheels has cryptography 50.0.2 for linux-armv7l: --extra-index-url https://www.piwheels.org/simple."""
    labels = [t.label(multi_py) for t in h.wheels]
    return f"piwheels has {pkg.name} {h.version} for {', '.join(labels)}: --extra-index-url {INDEX}"
