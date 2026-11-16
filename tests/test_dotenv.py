"""`.env` fills keys the environment lacks and never overrides one it has."""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.dotenv import load_dotenv


@pytest.fixture(autouse=True)
def _allow_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTODECK_NO_DOTENV", raising=False)
    for name in ("AD_TEST_A", "AD_TEST_B", "AD_TEST_C", "AD_TEST_D"):
        monkeypatch.delenv(name, raising=False)


def test_values_load_in_every_common_spelling(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "# comment\n\nAD_TEST_A=plain\nAD_TEST_B = spaced\nexport AD_TEST_C='quoted'\n"
        'AD_TEST_D="double"\n',
        encoding="utf-8",
    )
    import os

    assert load_dotenv(env) == ["AD_TEST_A", "AD_TEST_B", "AD_TEST_C", "AD_TEST_D"]
    assert [os.environ[f"AD_TEST_{c}"] for c in "ABCD"] == [
        "plain",
        "spaced",
        "quoted",
        "double",
    ]


def test_the_environment_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    monkeypatch.setenv("AD_TEST_A", "from-shell")
    env = tmp_path / ".env"
    env.write_text("AD_TEST_A=from-file\n", encoding="utf-8")
    assert load_dotenv(env) == []
    assert os.environ["AD_TEST_A"] == "from-shell"


def test_opt_out_and_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    env.write_text("AD_TEST_A=x\n", encoding="utf-8")
    monkeypatch.setenv("AUTODECK_NO_DOTENV", "1")
    assert load_dotenv(env) == []
    monkeypatch.delenv("AUTODECK_NO_DOTENV")
    assert load_dotenv(tmp_path / "absent.env") == []
