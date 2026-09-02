from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.asset import Asset
from models.watchlist import Watchlist, WatchlistItem


class WatchlistError(Exception):
    """Watchlist operation could not be completed."""


def create_watchlist(
    session: Session, name: str, kind: str = "personal", description: str | None = None
) -> Watchlist:
    if get_watchlist_by_name(session, name) is not None:
        raise WatchlistError(f"Watchlist {name!r} already exists")
    watchlist = Watchlist(name=name, kind=kind, description=description)
    session.add(watchlist)
    session.flush()
    return watchlist


def get_watchlist_by_name(session: Session, name: str) -> Watchlist | None:
    return session.scalars(select(Watchlist).where(Watchlist.name == name)).first()


def list_watchlists(session: Session, kind: str | None = None) -> list[Watchlist]:
    query = select(Watchlist).order_by(Watchlist.name)
    if kind:
        query = query.where(Watchlist.kind == kind)
    return list(session.scalars(query).all())


def add_item(
    session: Session, watchlist: Watchlist, asset: Asset, note: str | None = None
) -> WatchlistItem:
    """Add an asset. Idempotent: re-adding updates the note instead of
    creating a duplicate row.
    """
    existing = session.scalars(
        select(WatchlistItem).where(
            WatchlistItem.watchlist_id == watchlist.id,
            WatchlistItem.asset_id == asset.id,
        )
    ).first()
    if existing is not None:
        if note is not None:
            existing.note = note
        session.flush()
        return existing

    item = WatchlistItem(watchlist_id=watchlist.id, asset_id=asset.id, note=note)
    session.add(item)
    session.flush()
    return item


def remove_item(session: Session, watchlist: Watchlist, asset: Asset) -> bool:
    item = session.scalars(
        select(WatchlistItem).where(
            WatchlistItem.watchlist_id == watchlist.id,
            WatchlistItem.asset_id == asset.id,
        )
    ).first()
    if item is None:
        return False
    session.delete(item)
    session.flush()
    return True


def get_watchlist_assets(session: Session, watchlist: Watchlist) -> list[Asset]:
    return list(
        session.scalars(
            select(Asset)
            .join(WatchlistItem, WatchlistItem.asset_id == Asset.id)
            .where(WatchlistItem.watchlist_id == watchlist.id)
            .order_by(Asset.ticker)
        ).all()
    )


def get_watched_asset_ids(session: Session) -> set[int]:
    """Every asset on any watchlist -- used to prioritize ingestion/research."""
    return set(session.scalars(select(WatchlistItem.asset_id)).all())
