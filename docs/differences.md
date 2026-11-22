<!--
When an issue listed on this page is resolved, update or remove its entry in the corresponding pull request.
-->

# Where wheelgap differs from pip and uv

wheelgap's goal is to predict whether `pip` or `uv` will install a prebuilt wheel, build from source, or fail. In most cases, wheelgap's answer matches the installer exactly. However, there are known scenarios where wheelgap's model is intentionally simpler than a full installer or package resolver, or where behavior is tracked for a future release.

This page summarizes each difference, what wheelgap assumes, what installers do, and when it affects the reported verdict.

---

## Version ranges

- **What wheelgap assumes:** A version range or bare name in a requirements file is evaluated at the newest matching release published on the index (see [Version ranges](how-it-works.md#version-ranges)). With `--deps`, wheelgap resolves dependencies top-down without full backtracking.
- **What pip and uv do:** Full package resolvers (`pip` 24.3+, `uv` 0.5+) solve the entire dependency graph simultaneously, selecting a mutually compatible version that may be older than the latest release.
- **When it changes the answer:** A package whose newest release lacks wheels may have older compatible releases with wheels that a full resolver would pick.
- **Tracking:** Documented in [How it works](how-it-works.md#version-ranges) and tracked for unpinned Dockerfile requirements in [#643](https://github.com/wheelgap/wheelgap/issues/643).

## Python patch releases

- **What wheelgap assumes:** Passing `-p 3.13` evaluates `Requires-Python` metadata assuming the newest patch level of that Python series (`3.13.99`).
- **What pip and uv do:** Installers compare `Requires-Python` against the exact runtime Python version in the active environment (e.g., `3.13.0` or `3.13.2`).
- **When it changes the answer:** A package requiring `Requires-Python: >=3.13.2` is accepted by wheelgap for `-p 3.13`, but an installation running on Python `3.13.0` or `3.13.1` refuses it.
- **Tracking:** Tracked in [#638](https://github.com/wheelgap/wheelgap/issues/638).

## Pre-installed packages

- **What wheelgap assumes:** Under `--dockerfile-inputs`, each requirement file is evaluated as a clean, fresh install into the target image.
- **What pip and uv do:** `pip install` inspects the image's existing `site-packages` directory and leaves an already installed package untouched if it satisfies the requirement.
- **When it changes the answer:** A pre-installed dependency whose newest release on the index lacks wheels is flagged as a source build or gap by wheelgap, whereas pip skips installing or compiling it.
- **Tracking:** Tracked in [#636](https://github.com/wheelgap/wheelgap/issues/636).

## Requirements file hashes

- **What wheelgap assumes:** `--hash` options in requirements files (`--hash=sha256:...`) are ignored during file selection.
- **What pip and uv do:** `pip` and `uv` restrict candidate downloads strictly to files matching one of the specified hashes. If a hash is provided only for the sdist, pip builds from source even when matching wheels exist on PyPI.
- **When it changes the answer:** A package pinned with only an sdist hash is reported by wheelgap as `wheel` if prebuilt wheels exist, while pip and uv build it from source.
- **Tracking:** Tracked in [#633](https://github.com/wheelgap/wheelgap/issues/633).

## Additional index URLs

- **What wheelgap assumes:** `--index-url`, `--extra-index-url`, and `--find-links` options inside requirements files are not read; packages are checked against PyPI (or the global `--index-url` passed to wheelgap).
- **What pip and uv do:** `pip` and `uv` query all specified index URLs and find-links locations, finding prebuilt wheels published on external or private repositories (such as PyTorch or CUDA package indexes).
- **When it changes the answer:** Dependencies hosted only on an external index appear as `missing` or `source` when PyPI lacks a matching prebuilt wheel.
- **Tracking:** Tracked in [#632](https://github.com/wheelgap/wheelgap/issues/632).

## Pre-releases and prefer-binary

- **What wheelgap assumes:** `--pre` and `--prefer-binary` options in requirements files are skipped.
- **What pip and uv do:** `pip` with `--pre` considers alpha, beta, and release candidates; with `--prefer-binary`, pip chooses an older release that has a prebuilt wheel over a newer release that only offers an sdist.
- **When it changes the answer:** A package where only a pre-release has prebuilt wheels, or where `--prefer-binary` would pick an older wheel, is reported as `source`.
- **Tracking:** Tracked in [#634](https://github.com/wheelgap/wheelgap/issues/634).

## User and system configuration

- **What wheelgap assumes:** Configuration files (`pip.conf`, `~/.config/uv/uv.toml`) and environment variables (`PIP_*`, `UV_*`) on the machine running wheelgap are never read.
- **What pip and uv do:** Installers load configuration from user and system configuration paths and respect all environment variables that configure index URLs, proxies, and caching.
- **When it changes the answer:** Custom indexes or local environment variables that affect package resolution in a local environment do not alter wheelgap's output.
- **Tracking:** See [Configuration](configuration.md) and tracked for Dockerfile environments in [#642](https://github.com/wheelgap/wheelgap/issues/642).

## uv.lock Requires-Python bounds

- **What wheelgap assumes:** `uv.lock` is evaluated following `uv sync`, which enforces only the lower bound of `Requires-Python`. When run with `--online`, files excluded by an upper bound (such as `<3.15` or `!=3.14.*`) are still checked, and the report notes where pip would refuse them.
- **What pip and uv do:** `uv sync` installs the locked release ignoring upper bounds; `pip install` strictly enforces both lower and upper bounds of `Requires-Python`.
- **When it changes the answer:** A locked package whose `Requires-Python` specifies `<3.15` will install under `uv sync` on Python 3.15, but pip would refuse to install it.
- **Tracking:** Documented in [uv.lock](inputs.md#uvlock) and tracked in [#544](https://github.com/wheelgap/wheelgap/issues/544).

## File-name casing

- **What wheelgap assumes:** Files referenced in inputs (such as `-r requirements.txt` or Dockerfile `COPY` instructions) are resolved using the host operating system's filesystem rules.
- **What pip and uv do:** In case-sensitive environments (such as standard Linux Docker containers), case mismatches (e.g. `Requirements.txt` vs `requirements.txt`) fail immediately.
- **When it changes the answer:** Running wheelgap on macOS or Windows may find a file whose casing differs from the repository filename, whereas building the Docker container on Linux fails.
- **Tracking:** Tracked for Dockerfile inputs in [#635](https://github.com/wheelgap/wheelgap/issues/635).

## Source builds

- **What wheelgap assumes:** A `source` status indicates that PyPI publishes an sdist for that version, meaning an installer will attempt a source build.
- **What pip and uv do:** `pip` and `uv` invoke PEP 517 build backends, which compile C, C++, or Rust extensions using host compilers and system header libraries (e.g. `gcc`, `libpq-dev`).
- **When it changes the answer:** wheelgap reports whether a source build will be attempted, not whether the build will succeed on the target machine.
- **Tracking:** Documented in [FAQ: Why does it say source](faq.md#why-does-it-say-source-when-pip-installs-a-wheel).

## Constraints files

- **What wheelgap assumes:** Pinned dependencies (`name==1.2.3`) in requirements files are checked at the pinned version directly without checking them against `-c constraints.txt` lines in the same file.
- **What pip and uv do:** `pip` validates pinned requirements against constraints files, and fails with a version conflict if a pin contradicts a constraint.
- **When it changes the answer:** wheelgap reports wheel coverage for the pinned version even if pip would reject the install due to a conflicting constraint.
- **Tracking:** Tracked in [#631](https://github.com/wheelgap/wheelgap/issues/631).
