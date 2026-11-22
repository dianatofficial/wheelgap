<!--
When an issue listed on this page is resolved, update or remove its entry in the corresponding pull request.
-->

# Where wheelgap differs from pip and uv

wheelgap's goal is to predict whether `pip` or `uv` will install a prebuilt wheel, build from source, or fail. In most cases, wheelgap's answer matches the installer exactly. However, there are known scenarios where wheelgap's model is intentionally simpler than a full installer or package resolver, or where behavior is tracked for a future release.

This page summarizes each difference, what wheelgap assumes, what installers do, and when it affects the reported verdict. Installer behavior is as checked in the linked issue (pip 26.3 and uv 0.13.1 unless it says otherwise) or as stated in the linked docs section.

---

## Version ranges

- **What wheelgap assumes:** A version range or bare name in a requirements file is evaluated at the newest matching release published on the index, picked by pip's rule (see [Version ranges](how-it-works.md#version-ranges)). With `--deps`, wheelgap resolves dependencies top-down without backtracking.
- **What pip and uv do:** Their resolvers solve the whole set of requirements together and backtrack when two requirements conflict, so another requirement's bound can make them pick an older release than the newest one that matches.
- **When it changes the answer:** When a resolver settles on an older release, its files can differ from the newest release's in either direction: an older release without the wheel the newest has (wheelgap says `wheel`, the install builds or fails), or the reverse. Pin the versions you install to check exactly those.
- **Tracking:** Backtracking is by design; documented in [How it works](how-it-works.md#version-ranges). uv's rule for picking a release for one range also differs from pip's (it ignores a `Requires-Python` upper bound, for example), which is why `--dockerfile-inputs` refuses an unpinned requirement under `uv pip install`; reading those ranges the way uv does is [#643](https://github.com/wheelgap/wheelgap/issues/643).

## Python patch releases

- **What wheelgap assumes:** Passing `-p 3.13` evaluates `Requires-Python` metadata assuming the newest patch level of that Python series (`3.13.99`).
- **What pip and uv do:** Installers compare `Requires-Python` against the exact runtime Python version in the active environment (e.g., `3.13.0` or `3.13.2`).
- **When it changes the answer:** A package requiring `Requires-Python: >=3.13.2` is accepted by wheelgap for `-p 3.13`, but an installation running on Python `3.13.0` or `3.13.1` refuses it.
- **Tracking:** Tracked in [#638](https://github.com/wheelgap/wheelgap/issues/638).

## Pre-installed packages

- **What wheelgap assumes:** Under `--dockerfile-inputs`, each requirement file is evaluated as a clean, fresh install into the target image.
- **What pip and uv do:** Without `--upgrade`, `pip install` and `uv pip install` leave a package already installed in the image (from the base image or an earlier `RUN`) untouched if it satisfies the requirement.
- **When it changes the answer:** Only for unpinned requirements on a line without `--upgrade`: a pre-installed dependency whose newest release on the index lacks wheels is flagged as a source build or gap by wheelgap, whereas pip skips installing or compiling it.
- **Tracking:** Tracked in [#636](https://github.com/wheelgap/wheelgap/issues/636).

## Requirements file hashes

- **What wheelgap assumes:** `--hash` options in requirements files (`--hash=sha256:...`) are ignored during file selection.
- **What pip and uv do:** `pip` and `uv` restrict candidate downloads strictly to files matching one of the specified hashes. If a hash is provided only for the sdist, pip builds from source even when matching wheels exist on PyPI.
- **When it changes the answer:** A package pinned with only an sdist hash is reported by wheelgap as `wheel` if prebuilt wheels exist, while pip and uv build it from source.
- **Tracking:** Tracked in [#633](https://github.com/wheelgap/wheelgap/issues/633).

## Additional index URLs

- **What wheelgap assumes:** `--index-url`, `--extra-index-url`, and `--find-links` options inside requirements files are not read; packages are checked against PyPI (or the `--index-url` passed to wheelgap).
- **What pip and uv do:** `pip` and `uv` query the indexes and find-links locations the file names, finding prebuilt wheels published on external or private repositories (such as PyTorch or CUDA package indexes).
- **When it changes the answer:** A package's files on the other index can differ from PyPI's: a wheel published only there is not seen, and a private package with a namesake on PyPI is judged by the PyPI project's files.
- **Tracking:** Tracked in [#632](https://github.com/wheelgap/wheelgap/issues/632).

## Pre-releases and prefer-binary

- **What wheelgap assumes:** `--pre` and `--prefer-binary` lines in requirements files are skipped, so an unpinned requirement is checked at the newest stable release (a pre-release counts only when no stable release matches).
- **What pip does:** With `--pre`, pip takes the newest release including alphas, betas and release candidates; with `--prefer-binary`, it takes an older release that has a wheel over a newer one that only has an sdist. uv ignores both lines with a warning.
- **When it changes the answer:** pip installs a different release from the one wheelgap checked, so any status can be off in either direction: for example the stable release has a wheel (`wheel`) but the pre-release pip installs under `--pre` has none.
- **Tracking:** Tracked in [#634](https://github.com/wheelgap/wheelgap/issues/634).

## User and system configuration

- **What wheelgap assumes:** User and system configuration files (`pip.conf` or `pip.ini`, `~/.config/uv/uv.toml`, `/etc/uv/uv.toml`) are not read, and `PIP_*` and `UV_*` environment variables never change which files are checked. Some of those variables are read only to refuse or skip a feature whose answer they would make wrong, such as `--deps` under `PIP_INDEX_URL`, and to decide which package names may be sent to PyPI (see [Which package names leave the run](how-it-works.md#pypi-origin)).
- **What pip and uv do:** Installers load configuration from user and system configuration paths and respect environment variables that set index URLs and other options.
- **When it changes the answer:** If the installing machine's configuration points pip or uv at another index or changes how files are picked, wheelgap's answer is still PyPI's (or that of the `--index-url` passed to wheelgap).
- **Tracking:** Documented in [Which package names leave the run](how-it-works.md#pypi-origin).

## uv.lock Requires-Python bounds

- **What wheelgap assumes:** `uv.lock` is evaluated following `uv sync`, with and without `--online` (after 0.13.0; 0.13.0 followed pip with `--online`), which checks only the lower bound of `Requires-Python`. A file excluded only by an upper bound (such as `<3.15` or `!=3.15.*`) still counts. With `--online`, the report also says where pip would refuse such a file; without it the lock doesn't record each file's `Requires-Python`, so wheelgap can't tell.
- **What pip and uv do:** `uv sync` installs the locked release ignoring upper bounds; `pip install` (from a requirements file exported from the lock, for example) enforces both lower and upper bounds of `Requires-Python`.
- **When it changes the answer:** A locked package whose `Requires-Python` specifies `<3.15` will install under `uv sync` on Python 3.15, but pip would refuse to install it.
- **Tracking:** Documented in [uv.lock](inputs.md#uvlock); the rule was settled in [#544](https://github.com/wheelgap/wheelgap/issues/544).

## File-name casing

- **What wheelgap assumes:** A file a requirements file names with `-r` or `-c` is found as the host's file system finds it. `--dockerfile-inputs` matches `COPY` paths with exact case on every host (after 0.13.0).
- **What pip and uv do:** On a case-sensitive file system (such as Linux, and a Linux Docker build), a name that differs only in case (`Base.txt` vs `base.txt`) is not found.
- **When it changes the answer:** Running `wheelgap requirements.txt` on macOS or Windows can follow `-r Base.txt` to `base.txt`, where pip on Linux stops with an error.
- **Tracking:** Listed as a later step in [#635](https://github.com/wheelgap/wheelgap/issues/635), which fixed the Dockerfile case.

## Source builds

- **What wheelgap assumes:** A `source` status indicates that the index publishes an sdist for that version, meaning an installer will attempt a source build.
- **What pip and uv do:** `pip` and `uv` invoke PEP 517 build backends, which compile C, C++, or Rust extensions using host compilers and system header libraries (e.g. `gcc`, `libpq-dev`).
- **When it changes the answer:** wheelgap reports whether a source build will be attempted, not whether the build will succeed on the target machine.
- **Tracking:** None; this is by design.

## Constraints files

- **What wheelgap assumes:** A requirement is checked without testing it against the `-c constraints.txt` file it is installed with. A pin (`idna==3.6`) is checked at its own version, and a range (`idna>=3.8`) is checked at the constraint's pin (`idna==3.7`) even when the pin is outside the range.
- **What pip and uv do:** `pip install` and `uv pip install` apply the constraint to the requirement and refuse the install when the two conflict.
- **When it changes the answer:** wheelgap reports wheel coverage for a version even though pip and uv refuse the install. `--deps` resolves the set and catches the conflict.
- **Tracking:** Tracked in [#631](https://github.com/wheelgap/wheelgap/issues/631).
