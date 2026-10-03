"""The models chosen in the UI survive a restart (no terminal needed to switch them)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autodeck.ui import api
from autodeck.ui.api import Roots, UIError, restore_env, set_env


def _roots(tmp_path: Path) -> Roots:
    return Roots(profile=tmp_path / "profile.json", env="dev")


def test_a_chosen_environment_is_remembered_and_restored(tmp_path: Path) -> None:
    set_env(_roots(tmp_path), "dev-mistral")
    saved = json.loads((tmp_path / api.SETTINGS_FILENAME).read_text(encoding="utf-8"))
    assert saved == {"env": "dev-mistral"}

    fresh = _roots(tmp_path)
    restore_env(fresh)
    assert fresh.env == "dev-mistral"


def test_an_unknown_environment_is_refused_and_not_saved(tmp_path: Path) -> None:
    with pytest.raises(UIError):
        set_env(_roots(tmp_path), "nope")
    assert not (tmp_path / api.SETTINGS_FILENAME).exists()


def test_a_saved_environment_that_no_longer_exists_is_ignored(tmp_path: Path) -> None:
    (tmp_path / api.SETTINGS_FILENAME).write_text('{"env": "retired"}', encoding="utf-8")
    roots = _roots(tmp_path)
    restore_env(roots)
    assert roots.env == "dev"


def test_settings_say_which_environments_lack_a_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    envs = {e["name"]: e for e in api.settings(_roots(tmp_path))["envs"]}
    assert envs["dev-mistral"]["missing_credentials"] == ["MISTRAL_API_KEY"]
