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
    assert piwheels.PLATFORMS == {"linux-armv7l", "linux-aarch64"}


def test_match_is_a_hint_only(capsys, fake_pypi):
    args = ["nowheels==0.9", "-t", "linux-armv7l", "-t", "linux-aarch64", "-t", "linux-x86_64"]
    code_plain, out_plain, err_plain = run(capsys, *args, "-p", "3.13", "--explain")
    assert not piwheels_calls(fake_pypi)
    code, out, err = run(capsys, *args, *FLAGS)
    assert piwheels_calls(fake_pypi) == [API + "nowheels/json/"]
    hint = "piwheels has nowheels 0.9 for linux-armv7l, linux-aarch64: --extra-index-url https://www.piwheels.org/simple\n\n"
    assert hint in out
    assert code == code_plain == 1
    assert out.replace(hint, "") == out_plain and err == err_plain


def test_multi_python_label(capsys, fake_pypi):
    args = ["nowheels==0.9", "-t", "linux-armv7l", "-p", "3.12,3.13", "--explain", "--piwheels"]
    code, out, err = run(capsys, *args)
    # Both 3.12 and 3.13 have wheels on linux-armv7l in FAKE_PIWHEELS
    assert "piwheels has nowheels 0.9 for 3.12 linux-armv7l, 3.13 linux-armv7l: --extra-index-url https://www.piwheels.org/simple" in out


def test_json_output_matches_schema(capsys, fake_pypi):
    args = ["nowheels==0.9", "-t", "linux-armv7l", "-t", "linux-aarch64", "-t", "linux-x86_64", "-p", "3.13"]
    hints, _ = json_hints(capsys, *args, "--explain", "--piwheels")
    assert hints == {
        "nowheels": {
            "name": "nowheels",
            "version": "0.9",
            "wheels": {
                "linux-armv7l": ["nowheels-0.9-cp313-cp313-linux_armv7l.whl"],
                "linux-aarch64": ["nowheels-0.9-cp313-cp313-linux_aarch64.whl"],
            },
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
    assert cached == [
        "nowheels-0.9-cp313-cp313-linux_armv7l.whl",
        "nowheels-0.9-cp313-cp313-linux_aarch64.whl",
        "nowheels-0.9-cp312-cp312-linux_armv7l.whl",
    ]
