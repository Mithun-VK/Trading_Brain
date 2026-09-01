from __future__ import annotations

import pytest

import data.storage.session as session_module
import models
from config.settings import get_settings
from data.storage.session import get_engine, session_scope
from models.base import Base


@pytest.fixture(autouse=True)
def _sqlite_db(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    get_settings.cache_clear()
    session_module._engine = None
    session_module._SessionLocal = None

    Base.metadata.create_all(get_engine())
    yield
    session_module._engine = None
    session_module._SessionLocal = None
    get_settings.cache_clear()


def test_session_scope_commits() -> None:
    with session_scope() as session:
        session.add(models.Strategy(name="breakout-v1", rules={}))

    with session_scope() as session:
        assert session.query(models.Strategy).filter_by(name="breakout-v1").one_or_none()


def test_session_scope_rolls_back_on_error() -> None:
    with pytest.raises(ValueError):
        with session_scope() as session:
            session.add(models.Strategy(name="will-roll-back", rules={}))
            raise ValueError("boom")

    with session_scope() as session:
        assert session.query(models.Strategy).filter_by(name="will-roll-back").one_or_none() is None
