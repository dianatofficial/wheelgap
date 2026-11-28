# Rust extensions (PyO3 + maturin)

When a package grows a Rust extension, it stops being a `py3-none-any`
wheel: the compiled extension is tied to a Python ABI and a platform, so pip
can only install a prebuilt wheel that matches the interpreter and the
machine. Without one, pip falls back to the sdist and compiles the Rust on
the user's machine, which needs a Rust toolchain and a matching compiler.
This page is the checklist for shipping those wheels.

## Why it matters

A pure-Python package publishes one `py3-none-any` wheel and every platform
installs it. Add a Rust extension and that single wheel no longer works:
the compiled `.so`/`.pyd` is built for one Python ABI and one OS/arch/libc,
so each platform you support needs its own wheel. Miss one and the users on
that platform either compile from source (Rust toolchain required, slow,
fragile) or get no install at all.

## The matrix to build

Build one wheel per row. `windows-11-arm` is GitHub's native ARM64 Windows
runner; the Linux rows need both a glibc (manylinux) and a musl
(musllinux) build.

| Platform | Runner | wheelgap target |
| --- | --- | --- |
| Linux x86_64 (manylinux) | `ubuntu-latest` | `linux-x86_64` |
| Linux x86_64 (musllinux) | `ubuntu-latest` (musl container) | `musl-x86_64` |
| Linux aarch64 (manylinux) | `ubuntu-24.04-arm`, or QEMU | `linux-aarch64` |
| Linux aarch64 (musllinux) | `ubuntu-24.04-arm` (musl container) | `musl-aarch64` |
| macOS x86_64 | `macos-15-intel` | `macos-x86_64` |
| macOS arm64 | `macos-15` or newer | `macos-arm64` |
| Windows x64 | `windows-latest` | `win-amd64` |
| Windows arm64 | `windows-11-arm` | `win-arm64` |

Use [PyO3/maturin-action](https://github.com/PyO3/maturin-action) to drive
maturin on each runner. A minimal build step for the Linux rows:

```yaml
- uses: PyO3/maturin-action@v1
  with:
    command: build
    manylinux: auto  # musllinux_1_2 for the musl rows
    args: --release --out dist -i python3.11 -i python3.12 -i python3.13 -i python3.14 -i python3.15 -i python3.14t -i python3.15t
```

`--out dist` matters: maturin writes to `target/wheels/` by default, and the
check below reads `dist/`. With `manylinux` set, the Action builds inside a
manylinux (or musllinux) container that already has these Pythons; without
it, it builds on the runner itself. The macOS and Windows runners don't have
every Python, so install them first (for example `actions/setup-python` with
each version, including `3.14t` and `3.15t`). See the Action's README for `target`,
`manylinux`, `container` and `rust-toolchain`, and the [maturin book](https://www.maturin.rs/) for local
builds and `maturin generate-ci`. Linking instead of repeating them keeps
this page short.

## Pythons

Pass the interpreters explicitly with `-i` / `--interpreter` instead of
`--find-interpreter`, so the set you ship is the set you check:

```bash
maturin build --release --out dist \
  -i python3.11 -i python3.12 -i python3.13 -i python3.14 -i python3.15 -i python3.14t -i python3.15t
```

Start at 3.11 if you ship `win-arm64`: CPython has no Windows ARM64 build
before 3.11, so a 3.10 in the list fails the `windows-11-arm` job and leaves
`3.10 win-arm64` as a gap in the check below.

Only list Pythons your PyO3 version supports. PyO3 checks the interpreter it
builds for and refuses a newer CPython than it knows, so with an older PyO3
the `3.15`/`3.15t` builds fail. Upgrade PyO3 first (its changelog says which
Pythons each release supports), or leave those versions out until you do.

!!! note
    An `abi3` wheel does not install on a free-threaded interpreter:
    free-threaded CPython needs `cp314-cp314t` wheels (or `abi3t` on 3.15+).
    If you ship `abi3` only, pass each free-threaded Python (`3.14t`, `3.15t`) so the gap shows up before
    release, not in a user's install. See
    [Wheels on free-threaded Python](free-threading.md).

## Check before you publish

Each runner builds only its own platform's wheel, so run the check in the
job that publishes, after collecting every build job's wheels (and the sdist,
from `maturin sdist --out dist`, if you ship one) into one `dist/` folder, for
example with `actions/download-artifact` and `merge-multiple: true`. Checked
inside a single build job, every other platform would count as dropped.

Run wheelgap on that `dist/` folder before uploading, with the Pythons and
targets you actually ship:

```bash
uvx wheelgap@latest --dist dist/ -p 3.11 -p 3.12 -p 3.13 -p 3.14 -p 3.15 -p 3.14t -p 3.15t \
  -t linux-x86_64,linux-aarch64,musl-x86_64,musl-aarch64,macos-x86_64,macos-arm64,win-amd64,win-arm64
```

It checks each file in `dist/` against the targets, compares with the last
release on PyPI, and fails if a target you had a wheel for got none this
time, or if any target has no wheel at all (as a lockfile gap would). In GitHub Actions the same check is the `dist` input:

```yaml
- uses: wheelgap/wheelgap@v0.14.0
  with:
    dist: dist
    args: -p 3.11 -p 3.12 -p 3.13 -p 3.14 -p 3.15 -p 3.14t -p 3.15t -t linux-x86_64,linux-aarch64,musl-x86_64,musl-aarch64,macos-x86_64,macos-arm64,win-amd64,win-arm64
```

See [Before a release](ci.md#before-a-release) and
[`--dist`](cli.md#dist) for what a dropped target means and the exit code.
