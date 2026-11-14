import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from testign import config

REPO = Path(__file__).resolve().parent.parent


def test_defaults_resolve_output_dir_under_home(tmp_path):
    cfg = config.defaults(tmp_path)
    assert Path(cfg["output_dir"]) == tmp_path / "Downloads"
    assert cfg["lang"] == "vi"
    assert cfg["master_ref"] == "master"
    assert cfg["develop_ref"] == "develop"
    assert set(cfg["backlog"]) == {"space", "project_key", "decisions_log_page"}


def test_default_output_dir_uses_real_home():
    assert Path(config.defaults()["output_dir"]) == Path.home() / "Downloads"


def test_first_load_creates_file_with_defaults(tmp_path):
    path = config.config_path(tmp_path)
    assert not path.exists()
    cfg = config.load(tmp_path)
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == cfg == config.defaults(tmp_path)


def test_overrides_merge_with_defaults(tmp_path):
    path = config.config_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"lang": "ja", "develop_ref": "release/2026", "backlog": {"space": "demo.backlog.com"}}),
        encoding="utf-8",
    )
    cfg = config.load(tmp_path)
    assert cfg["lang"] == "ja"
    assert cfg["develop_ref"] == "release/2026"
    assert cfg["master_ref"] == "master"
    assert cfg["backlog"] == {"space": "demo.backlog.com", "project_key": "", "decisions_log_page": ""}


def test_output_dir_tilde_is_expanded(tmp_path):
    path = config.config_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"output_dir": "~/qa-out"}), encoding="utf-8")
    assert Path(config.load(tmp_path)["output_dir"]) == Path.home() / "qa-out"


def test_invalid_json_raises_config_error(tmp_path):
    path = config.config_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(config.ConfigError):
        config.load(tmp_path)


def test_default_ticket_regex_matches_backlog_keys():
    rx = re.compile(config.DEFAULT_TICKET_ID_REGEX)
    assert rx.findall("fix: DEMO-12 and PROJ_X-3 done") == ["DEMO-12", "PROJ_X-3"]
    assert rx.findall("no ticket here") == []


def test_run_py_prints_config_with_temp_home(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path), USERPROFILE=str(tmp_path))
    out = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "run.py"), "config"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=True,
    )
    cfg = json.loads(out.stdout)
    assert Path(cfg["output_dir"]) == tmp_path / "Downloads"
    assert config.config_path(tmp_path).exists()


def test_run_py_reports_bad_config_without_traceback(tmp_path):
    path = config.config_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("[]", encoding="utf-8")
    env = dict(os.environ, HOME=str(tmp_path), USERPROFILE=str(tmp_path))
    out = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "run.py"), "config"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    assert out.returncode == 2
    assert "Traceback" not in out.stderr
    assert "JSON object" in out.stderr
