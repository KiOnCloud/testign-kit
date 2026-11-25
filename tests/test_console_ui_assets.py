"""Static checks on the console UI: strings, CSP-clean markup, vendored files, fonts, imports."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from testign.console import server as srv

UI = Path(srv.__file__).resolve().parent / "ui"
YOHAKU = UI / "vendor" / "yohaku"
LANGS = ("en", "ja")


def ui_files(*suffixes: str) -> list[Path]:
    return sorted(p for p in UI.rglob("*") if p.is_file() and p.suffix in suffixes)


def code_files() -> list[Path]:
    """Shipped modules and pages (the node tests under ui/tests/ are not served)."""
    return [p for p in ui_files(".mjs", ".html") if "tests" not in p.relative_to(UI).parts]


def load_dicts() -> dict[str, dict]:
    return {lang: json.loads((UI / "i18n" / f"{lang}.json").read_text(encoding="utf-8")) for lang in LANGS}


def test_i18n_dictionaries_have_the_same_keys_and_no_empty_values():
    dicts = load_dicts()
    keys = {lang: set(d) for lang, d in dicts.items()}
    assert keys["en"] == keys["ja"], sorted(keys["en"] ^ keys["ja"])
    for lang, d in dicts.items():
        for key, value in d.items():
            assert re.fullmatch(r"[a-z0-9_]+", key), (lang, key)
            assert isinstance(value, str) and value.strip(), (lang, key)


def test_placeholders_match_across_languages():
    dicts = load_dicts()
    for key, text in dicts["en"].items():
        expected = set(re.findall(r"\{(\w+)\}", text))
        assert set(re.findall(r"\{(\w+)\}", dicts["ja"][key])) == expected, key


def test_only_english_and_japanese_ship():
    assert sorted(p.name for p in (UI / "i18n").iterdir()) == ["en.json", "ja.json"]
    assert re.search(r'<html lang="en"', (UI / "index.html").read_text(encoding="utf-8"))


def test_every_literal_key_used_in_code_exists():
    known = set(load_dicts()["en"])
    used = set()
    for path in code_files():
        used |= set(re.findall(r"\bt\(\s*'([a-z0-9_]+)'", path.read_text(encoding="utf-8")))
    assert used, "no t('key') calls found"
    assert used <= known, sorted(used - known)


STYLE_ATTR = re.compile(r"""\sstyle\s*=\s*["'{]""", re.I)
HANDLER_ATTR = re.compile(r"""\son[a-z]+\s*=\s*["'{]""", re.I)
MARKUP_SINKS = re.compile(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\.style\.|setAttribute\(\s*'style'")


@pytest.mark.parametrize("path", ui_files(".mjs", ".html"), ids=lambda p: p.relative_to(UI).as_posix())
def test_no_inline_style_handlers_or_markup_sinks(path):
    text = path.read_text(encoding="utf-8")
    assert not STYLE_ATTR.search(text), "inline style attribute"
    assert not HANDLER_ATTR.search(text), "inline event handler attribute"
    if path.suffix == ".mjs":
        assert not MARKUP_SINKS.search(text), "markup sink or inline style in a module"


def test_html_has_no_inline_script_or_style():
    for path in ui_files(".html"):
        text = path.read_text(encoding="utf-8")
        assert "<style" not in text.lower()
        for tag in re.findall(r"<script\b[^>]*>(.*?)</script>", text, flags=re.S | re.I):
            assert not tag.strip(), f"inline script in {path.name}"
        assert re.search(r'<script type="module" src="/main.mjs"></script>', text)
        assert 'data-theme="light"' in text


def lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_vendored_yohaku_matches_lock():
    lock = json.loads((YOHAKU / "LOCK.json").read_text(encoding="utf-8"))
    assert re.fullmatch(r"[0-9a-f]{40}", lock["commit"]), lock["commit"]
    assert lock["source"] == f"https://github.com/KiOnCloud/qingyi-test-kit/tree/{lock['commit']}/qingyi/lab/static/yohaku"
    assert lock["version"]
    on_disk = {p.name for p in YOHAKU.iterdir() if p.suffix == ".css"}
    assert on_disk == set(lock["files"]) == {"tokens.css", "bundle.css"}
    for name, entry in lock["files"].items():
        assert lf_sha256(YOHAKU / name) == entry["sha256"], name
        assert isinstance(entry["changes"], list)


def test_css_loads_nothing_from_outside():
    for path in ui_files(".css"):
        text = path.read_text(encoding="utf-8")
        assert "@import" not in text, path.name
        assert not re.search(r"url\(\s*['\"]?(https?:)?//", text), path.name


def test_every_font_has_its_licence_and_every_face_points_at_a_file():
    fonts = UI / "fonts"
    licences = {"noto-sans": "OFL-NotoSans.txt"}
    woff = sorted(fonts.glob("*.woff2"))
    assert woff
    for path in woff:
        family = next((k for k in licences if path.name.startswith(k + "-")), None)
        assert family, f"{path.name} has no known family"
        assert (fonts / licences[family]).is_file(), f"{path.name} has no licence beside it"
    css = (UI / "app.css").read_text(encoding="utf-8")
    referenced = set(re.findall(r'url\("/fonts/([^"]+)"\)', css))
    assert referenced == {p.name for p in woff}
    assert css.count("unicode-range:") == len(woff)


def test_relative_imports_resolve():
    for path in ui_files(".mjs"):
        for spec in re.findall(r"""^\s*import\b[^'"]*['"](\.[^'"]+)['"]""", path.read_text(encoding="utf-8"), flags=re.M):
            assert (path.parent / spec).resolve().is_file(), f"{path.relative_to(UI)} imports missing {spec}"


def test_static_manifest_serves_the_ui_but_not_its_tests():
    manifest = srv.build_static_manifest(UI)
    for url in ("/", "/index.html", "/main.mjs", "/app.css", "/i18n/en.json", "/i18n/ja.json", "/vendor/yohaku/bundle.css",
                "/views/report.mjs", "/fonts/noto-sans-latin-400-normal.woff2", "/fonts/OFL-NotoSans.txt"):
        assert url in manifest, url
    assert not any(url.startswith("/tests/") for url in manifest)
    html = (UI / "index.html").read_text(encoding="utf-8")
    for ref in re.findall(r'(?:href|src)="(/[^"]+)"', html):
        assert ref in manifest, ref
