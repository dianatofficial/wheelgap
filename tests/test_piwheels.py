import json
import urllib.error

import pytest
from conftest import FAKE_PIWHEELS, piwheels_data, piwheels_file
from test_cli import _assert_matches_output_schema, run

from wheelgap import cache, piwheels, pypi

API = "https://www.piwheels.org/project/"
FLAGS = ["-p", "3.13", "--explain", "--piwheels"]


def piwheels_calls(calls):
    return [url for url in calls if url.startswith(API)]


def json_hints(capsys, *args):
    code, out, err = run(capsys, *args, "--json")
    data = json.loads(out)
    _assert_matches_output_schema(data)
    return {p["name"]: p.get("piwheels") for p in data["packages"]}, err


def test_platforms_are_the_pi_ones():
    # piwheels' platform tags are linux_armv6l and linux_armv7l: it has no aarch64 wheels.
    assert piwheels.PLATFORMS == {"linux-armv7l"}


def test_other_gaps_send_no_request(capsys, fake_pypi):
    args = ["nowheels==0.9", "-t", "linux-aarch64", "-t", "linux-x86_64", "-p", "3.13", "--explain"]
    code_plain, out_plain, err_plain = run(capsys, *args)
    code, out, err = run(capsys, *args, "--piwheels")
    assert not piwheels_calls(fake_pypi)
    assert (code, out, err) == (code_plain, out_plain, err_plain)


def test_match_is_a_hint_only(capsys, fake_pypi):
    args = ["nowheels==0.9", "-t", "linux-armv7l", "-t", "linux-aarch64", "-t", "linux-x86_64"]
    code_plain, out_plain, err_plain = run(capsys, *args, "-p", "3.13", "--explain")
    assert not piwheels_calls(fake_pypi)
    code, out, err = run(capsys, *args, *FLAGS)
    assert piwheels_calls(fake_pypi) == [API + "nowheels/json/"]
    hint = "piwheels has nowheels 0.9 for linux-armv7l: --extra-index-url https://www.piwheels.org/simple\n\n"
    assert hint in out
    assert code == code_plain == 1
    assert out.replace(hint, "") == out_plain and err == err_plain


def test_multi_python_label(capsys, fake_pypi):
    args = ["nowheels==0.9", "-t", "linux-armv7l", "-p", "3.12,3.13", "--explain", "--piwheels"]
    code, out, err = run(capsys, *args)
    # Both 3.12 and 3.13 have wheels on linux-armv7l in FAKE_PIWHEELS
    assert "piwheels has nowheels 0.9 for 3.12 linux-armv7l, 3.13 linux-armv7l: --extra-index-url " in out
    hints, _ = json_hints(capsys, *args)
    assert hints["nowheels"]["wheels"] == {
        "3.12 linux-armv7l": ["nowheels-0.9-cp312-cp312-linux_armv7l.whl"],
        "3.13 linux-armv7l": ["nowheels-0.9-cp313-cp313-linux_armv7l.whl"],
    }
    assert hints["nowheels"]["apt"] == ["libc6", "libssl3"]  # sorted, each once


def test_json_output_matches_schema(capsys, fake_pypi):
    args = ["nowheels==0.9", "-t", "linux-armv7l", "-t", "linux-aarch64", "-t", "linux-x86_64", "-p", "3.13"]
    hints, _ = json_hints(capsys, *args, "--explain", "--piwheels")
    assert hints == {
        "nowheels": {
            "name": "nowheels",
            "version": "0.9",
            "wheels": {"linux-armv7l": ["nowheels-0.9-cp313-cp313-linux_armv7l.whl"]},
            "apt": ["libc6", "libssl3"],
        }
    }
    code, out, _ = run(capsys, *args, "--json", "--explain", "--piwheels")
    plain_code, plain, _ = run(capsys, *args, "--json", "--explain")
    data = json.loads(out)
    assert all("piwheels" not in p for p in json.loads(plain)["packages"])
    for p in data["packages"]:
        del p["piwheels"]
    assert data == json.loads(plain) and code == plain_code


def test_piwheels_refuses_without_explain(capsys):
    with pytest.raises(SystemExit) as e:
        run(capsys, "nowheels==0.9", "--piwheels")
    assert e.value.code == 2 and "pass --explain too" in capsys.readouterr().err


def test_piwheels_refuses_offline(capsys, fake_pypi, fixtures):
    code, _, err = run(capsys, str(fixtures / "uvproj" / "uv.lock"), "-t", "linux-armv7l", "--offline", *FLAGS)
    assert code == 2 and "--offline: --piwheels would look packages up on piwheels.org" in err
    assert not fake_pypi


def test_piwheels_keeps_private_names_private(capsys, fake_pypi, tmp_path):
    p = tmp_path / "requirements.txt"
    p.write_text("--extra-index-url https://private.example/simple\nnowheels==0.9\n")
    code, out, err = run(capsys, str(p), "-t", "linux-armv7l", "-p", "3.13", "--explain", "--piwheels")
    assert not piwheels_calls(fake_pypi)
    assert "whose index isn't known to be PyPI (nowheels), so their names stay private" in err


def test_yanked_release_ignored(capsys, monkeypatch, fake_pypi):
    monkeypatch.setitem(
        FAKE_PIWHEELS,
        "nowheels",
        piwheels_data(
            "nowheels",
            {
                "0.9": {
                    "released": "2026-10-01 12:00:00",
                    "prerelease": False,
                    "yanked": True,
                    "skip_reason": "broken",
                    "files": {
                        "nowheels-0.9-cp313-cp313-linux_armv7l.whl": piwheels_file(
                            "nowheels-0.9-cp313-cp313-linux_armv7l.whl"
                        )
                    },
                }
            },
        ),
    )
    code, out, _ = run(capsys, "nowheels==0.9", "-t", "linux-armv7l", "-p", "3.13", "--explain", "--piwheels")
    assert "piwheels has nowheels" not in out


def test_piwheels_404_no_hint(capsys, monkeypatch, fake_pypi):
    monkeypatch.delitem(FAKE_PIWHEELS, "nowheels", raising=False)
    code, out, err = run(capsys, "nowheels==0.9", "-t", "linux-armv7l", "-p", "3.13", "--explain", "--piwheels")
    assert "piwheels has nowheels" not in out
    assert "couldn't check" not in err  # 404 is clean: no such package


def test_piwheels_unreachable(capsys, monkeypatch, fake_pypi):
    monkeypatch.setitem(FAKE_PIWHEELS, "nowheels", urllib.error.URLError(OSError("no route to host")))
    code, out, err = run(capsys, "nowheels==0.9", "-t", "linux-armv7l", "-p", "3.13", "--explain", "--piwheels")
    assert "piwheels has nowheels" not in out
    assert "couldn't check 1 package: nowheels" in err


def test_piwheels_too_large(capsys, monkeypatch, fake_pypi):
    monkeypatch.setitem(FAKE_PIWHEELS, "nowheels", pypi.ResponseTooLarge("over the cap"))
    code, out, err = run(capsys, "nowheels==0.9", "-t", "linux-armv7l", "-p", "3.13", "--explain", "--piwheels")
    assert "piwheels has nowheels" not in out
    assert "couldn't check 1 package: nowheels (answer too large" in err


def test_piwheels_cache_persistence(capsys, fake_pypi):
    args = ["nowheels==0.9", "-t", "linux-armv7l", "-p", "3.13", "--explain", "--piwheels"]
    run(capsys, *args)
    assert piwheels_calls(fake_pypi) == [API + "nowheels/json/"]
    # Second run hits cache
    run(capsys, *args)
    assert piwheels_calls(fake_pypi) == [API + "nowheels/json/"]
    cached = cache.load_piwheels("nowheels", "0.9")
    assert cached == {
        "nowheels-0.9-cp313-cp313-linux_armv7l.whl": ["libc6", "libssl3"],
        "nowheels-0.9-cp313-cp313-linux_armv6l.whl": ["libc6", "libssl3"],
        "nowheels-0.9-cp312-cp312-linux_armv7l.whl": ["libssl3", "libc6"],
    }


def test_other_python_s_wheel_is_no_hint(capsys, monkeypatch, fake_pypi):
    wheel = "nowheels-0.9-cp312-cp312-linux_armv7l.whl"
    release = {"yanked": False, "files": {wheel: piwheels_file(wheel, "cp312")}}
    monkeypatch.setitem(FAKE_PIWHEELS, "nowheels", piwheels_data("nowheels", {"0.9": release}))
    args = ["nowheels==0.9", "-t", "linux-armv7l", *FLAGS]
    _, out, _ = run(capsys, *args)
    assert piwheels_calls(fake_pypi) == [API + "nowheels/json/"] and "piwheels has" not in out
    hints, _ = json_hints(capsys, *args)
    assert hints == {"nowheels": None}


def test_other_index_runs_look_nothing_up(capsys, fake_pypi, fake_simple, monkeypatch):
    args = ["nowheels==0.9", "-t", "linux-armv7l", *FLAGS]
    _, out, err = run(capsys, *args, "--index-url", "https://pkgs.example.com/simple")
    assert fake_simple.calls and not piwheels_calls(fake_pypi) and "piwheels has" not in out
    assert "--piwheels looks nothing up" in err and "didn't look up" not in err
    monkeypatch.setenv("WHEELGAP_INDEX_URL", "https://mirror.example.com/pypi")
    _, out, err = run(capsys, *args)
    assert fake_pypi and not piwheels_calls(fake_pypi) and "--piwheels looks nothing up" in err


def test_quiet_suppresses_the_notes(capsys, fake_pypi, monkeypatch, tmp_path):
    monkeypatch.setitem(FAKE_PIWHEELS, "nowheels", TimeoutError("timed out"))
    (tmp_path / "requirements.txt").write_text("-i https://x.example/simple\nforked==1.0\n", encoding="utf-8")
    args = ["nowheels==0.9", str(tmp_path / "requirements.txt"), "-t", "linux-armv7l", *FLAGS, "--json"]
    _, _, err = run(capsys, *args)
    assert "couldn't check 1 package: nowheels (no usable answer)" in err and "didn't look up" in err
    _, _, err = run(capsys, *args, "-q")
    assert "piwheels" not in err
    _, _, err = run(capsys, *args, "-q", "--index-url", "https://x.example/simple")
    assert "piwheels" not in err


def test_names_are_quoted(monkeypatch):
    seen = []
    monkeypatch.setattr(pypi, "fetch_json", lambda url, **kw: seen.append((url, kw)) or {"releases": {}})
    assert piwheels.fetch("a/b?c", "1") == {}
    url, kw = seen[0]
    assert url == API + "a%2Fb%3Fc/json/"
    assert kw == {"timeout": piwheels.TIMEOUT, "attempts": 1, "max_bytes": piwheels.MAX_BYTES}
    assert piwheels.TIMEOUT <= 15 and piwheels.DEADLINE <= 30


@pytest.mark.parametrize("data", [[], "x", None, {}, {"releases": []}, {"releases": None}])
def test_unexpected_answers_are_a_failed_lookup(monkeypatch, data):
    with pytest.raises(ValueError):
        piwheels.parse_wheels(data, "nowheels", "0.9")
    monkeypatch.setattr(pypi, "fetch_json", lambda url, **kw: data)
    assert piwheels.fetch("nowheels", "0.9") is None


def _release(*filenames, **info):
    return {"releases": {"0.9.0": {"yanked": False, "files": {f: {**piwheels_file(f), **info} for f in filenames}}}}


def test_parse_wheels_matches_equal_versions():
    # The release is listed as 0.9.0 and the checked version is 0.9: the same version.
    wheels = ["nowheels-0.9.0-cp313-cp313-linux_armv7l.whl", "nowheels-0.9-cp313-cp313-linux_armv7l.whl"]
    assert list(piwheels.parse_wheels(_release(*wheels), "nowheels", "0.9")) == wheels
    assert piwheels.parse_wheels(_release(*wheels), "nowheels", "0.9.1") == {}


def test_parse_wheels_keeps_only_this_release_s_wheels():
    good = "NoWheels-0.9-cp313-cp313-linux_armv7l.whl"  # the same name, spelt another way
    others = [
        "nowheels-0.9.tar.gz",  # not a wheel
        "nowheels-0.9.zip",
        "nowheels-0.9-cp313-linux_armv7l.whl",  # not a valid wheel filename
        "nowheels-0.8-cp313-cp313-linux_armv7l.whl",  # another version
        "otherpkg-0.9-cp313-cp313-linux_armv7l.whl",  # another package
    ]
    assert list(piwheels.parse_wheels(_release(good, *others), "nowheels", "0.9")) == [good]


@pytest.mark.parametrize("field", ["file_url", "builder_abi", "platform"])
def test_parse_wheels_skips_files_missing_a_field(field):
    data = _release("nowheels-0.9-cp313-cp313-linux_armv7l.whl")
    del data["releases"]["0.9.0"]["files"]["nowheels-0.9-cp313-cp313-linux_armv7l.whl"][field]
    assert piwheels.parse_wheels(data, "nowheels", "0.9") == {}


@pytest.mark.parametrize(
    "release",
    [None, "x", {"yanked": True, "files": {}}, {"yanked": False}, {"yanked": False, "files": []}],
)
def test_parse_wheels_odd_or_yanked_release_has_none(release):
    assert piwheels.parse_wheels({"releases": {"0.9": release}}, "nowheels", "0.9") == {}


def test_parse_wheels_reads_apt_dependencies():
    wheel = "nowheels-0.9-cp313-cp313-linux_armv7l.whl"
    assert piwheels.parse_wheels(_release(wheel, apt_dependencies=["libc6", 3]), "nowheels", "0.9") == {
        wheel: ["libc6"]
    }
    assert piwheels.parse_wheels(_release(wheel, apt_dependencies=None), "nowheels", "0.9") == {wheel: []}
    assert piwheels.parse_wheels({"releases": {}}, "nowheels", "0.9") == {}  # no such version
