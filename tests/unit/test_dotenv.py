from __future__ import annotations

import os

from services.common import dotenv


def test_load_reads_key_value_pairs(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# комментарий\n"
        "\n"
        "DOTENV_TEST_KEY=value\n"
        "DOTENV_TEST_SPACED =  v 2 \n"
        "не пара\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("DOTENV_TEST_KEY", raising=False)
    monkeypatch.delenv("DOTENV_TEST_SPACED", raising=False)
    monkeypatch.setattr(dotenv, "ENV_FILE", env)

    dotenv.load()

    assert os.environ["DOTENV_TEST_KEY"] == "value"
    assert os.environ["DOTENV_TEST_SPACED"] == "v 2"


def test_real_environment_wins_over_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("DOTENV_TEST_WINS=file\n", encoding="utf-8")
    monkeypatch.setenv("DOTENV_TEST_WINS", "shell")
    monkeypatch.setattr(dotenv, "ENV_FILE", env)

    dotenv.load()

    assert os.environ["DOTENV_TEST_WINS"] == "shell"


def test_missing_file_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(dotenv, "ENV_FILE", tmp_path / "absent.env")
    dotenv.load()
