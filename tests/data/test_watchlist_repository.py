from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import models
from data.storage.watchlist_repository import (
    WatchlistError,
    add_item,
    create_watchlist,
    get_watched_asset_ids,
    get_watchlist_assets,
    get_watchlist_by_name,
    list_watchlists,
    remove_item,
)
from models.base import Base


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _asset(session: Session, ticker: str) -> models.Asset:
    asset = models.Asset(ticker=ticker, exchange="NSE", asset_type="equity", name=ticker)
    session.add(asset)
    session.flush()
    return asset


def test_create_and_fetch_watchlist(session: Session) -> None:
    created = create_watchlist(session, "AI", kind="theme", description="AI supply chain")
    session.commit()

    found = get_watchlist_by_name(session, "AI")
    assert found is not None
    assert found.id == created.id
    assert found.kind == "theme"


def test_duplicate_watchlist_name_is_rejected(session: Session) -> None:
    create_watchlist(session, "Banking")
    session.commit()

    with pytest.raises(WatchlistError, match="already exists"):
        create_watchlist(session, "Banking")


def test_list_watchlists_filters_by_kind(session: Session) -> None:
    create_watchlist(session, "AI", kind="theme")
    create_watchlist(session, "Banking", kind="sector")
    create_watchlist(session, "High Conviction", kind="personal")
    session.commit()

    assert [w.name for w in list_watchlists(session)] == ["AI", "Banking", "High Conviction"]
    assert [w.name for w in list_watchlists(session, kind="theme")] == ["AI"]


def test_add_and_list_items(session: Session) -> None:
    watchlist = create_watchlist(session, "Indian Manufacturing", kind="theme")
    reliance = _asset(session, "RELIANCE")
    tata = _asset(session, "TATASTEEL")
    add_item(session, watchlist, reliance, note="refining cycle")
    add_item(session, watchlist, tata)
    session.commit()

    assets = get_watchlist_assets(session, watchlist)
    assert [a.ticker for a in assets] == ["RELIANCE", "TATASTEEL"]


def test_adding_the_same_asset_twice_updates_instead_of_duplicating(session: Session) -> None:
    watchlist = create_watchlist(session, "AI")
    asset = _asset(session, "NVDA")

    add_item(session, watchlist, asset, note="first")
    add_item(session, watchlist, asset, note="second")
    session.commit()

    items = session.query(models.WatchlistItem).all()
    assert len(items) == 1
    assert items[0].note == "second"


def test_remove_item(session: Session) -> None:
    watchlist = create_watchlist(session, "AI")
    asset = _asset(session, "NVDA")
    add_item(session, watchlist, asset)
    session.commit()

    assert remove_item(session, watchlist, asset) is True
    session.commit()
    assert get_watchlist_assets(session, watchlist) == []


def test_removing_a_missing_item_reports_false(session: Session) -> None:
    watchlist = create_watchlist(session, "AI")
    asset = _asset(session, "NVDA")
    session.commit()

    assert remove_item(session, watchlist, asset) is False


def test_an_asset_can_belong_to_several_watchlists(session: Session) -> None:
    theme = create_watchlist(session, "AI", kind="theme")
    conviction = create_watchlist(session, "High Conviction", kind="personal")
    asset = _asset(session, "NVDA")

    add_item(session, theme, asset)
    add_item(session, conviction, asset)
    session.commit()

    assert get_watchlist_assets(session, theme)[0].ticker == "NVDA"
    assert get_watchlist_assets(session, conviction)[0].ticker == "NVDA"


def test_get_watched_asset_ids_is_deduplicated(session: Session) -> None:
    theme = create_watchlist(session, "AI", kind="theme")
    conviction = create_watchlist(session, "High Conviction")
    nvda = _asset(session, "NVDA")
    reliance = _asset(session, "RELIANCE")
    add_item(session, theme, nvda)
    add_item(session, conviction, nvda)
    add_item(session, conviction, reliance)
    session.commit()

    assert get_watched_asset_ids(session) == {nvda.id, reliance.id}


def test_deleting_a_watchlist_removes_its_items(session: Session) -> None:
    watchlist = create_watchlist(session, "AI")
    add_item(session, watchlist, _asset(session, "NVDA"))
    session.commit()

    session.delete(watchlist)
    session.commit()

    assert session.query(models.WatchlistItem).count() == 0
