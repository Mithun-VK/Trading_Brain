"""Watchlist API. Transport only -- all behaviour lives in
`data.storage.watchlist_repository`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.dependencies import get_session
from apps.api.routers._common import get_asset_or_404
from apps.api.schemas_v2 import (
    WatchlistCreate,
    WatchlistItemCreate,
    WatchlistItemOut,
    WatchlistOut,
    WatchlistUpdate,
)
from data.storage.watchlist_repository import (
    WatchlistError,
    add_item,
    create_watchlist,
    list_watchlists,
    remove_item,
)
from models.watchlist import Watchlist

router = APIRouter(tags=["watchlists"])


def _get_or_404(session: Session, watchlist_id: int) -> Watchlist:
    watchlist = session.get(Watchlist, watchlist_id)
    if watchlist is None:
        raise HTTPException(status_code=404, detail=f"No watchlist with id {watchlist_id}")
    return watchlist


def _to_out(watchlist: Watchlist, include_items: bool = True) -> WatchlistOut:
    items = [
        WatchlistItemOut(
            asset_id=item.asset_id,
            ticker=item.asset.ticker,
            name=item.asset.name,
            note=item.note,
            added_at=item.added_at,
        )
        for item in sorted(watchlist.items, key=lambda i: i.asset.ticker)
    ]
    return WatchlistOut(
        id=watchlist.id,
        name=watchlist.name,
        description=watchlist.description,
        kind=watchlist.kind,
        item_count=len(items),
        items=items if include_items else [],
        created_at=watchlist.created_at,
        updated_at=watchlist.updated_at,
    )


@router.get("/watchlists", response_model=list[WatchlistOut])
def list_all(
    kind: str | None = None, session: Session = Depends(get_session)
) -> list[WatchlistOut]:
    return [_to_out(w, include_items=False) for w in list_watchlists(session, kind=kind)]


@router.post("/watchlists", response_model=WatchlistOut, status_code=201)
def create(payload: WatchlistCreate, session: Session = Depends(get_session)) -> WatchlistOut:
    try:
        watchlist = create_watchlist(
            session, payload.name, kind=payload.kind, description=payload.description
        )
    except WatchlistError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    return _to_out(watchlist)


@router.get("/watchlists/{watchlist_id}", response_model=WatchlistOut)
def get_one(watchlist_id: int, session: Session = Depends(get_session)) -> WatchlistOut:
    return _to_out(_get_or_404(session, watchlist_id))


@router.patch("/watchlists/{watchlist_id}", response_model=WatchlistOut)
def update(
    watchlist_id: int, payload: WatchlistUpdate, session: Session = Depends(get_session)
) -> WatchlistOut:
    watchlist = _get_or_404(session, watchlist_id)

    if payload.name is not None and payload.name != watchlist.name:
        from data.storage.watchlist_repository import get_watchlist_by_name

        if get_watchlist_by_name(session, payload.name) is not None:
            raise HTTPException(
                status_code=409, detail=f"Watchlist {payload.name!r} already exists"
            )
        watchlist.name = payload.name
    if payload.description is not None:
        watchlist.description = payload.description
    if payload.kind is not None:
        if payload.kind not in {"theme", "sector", "personal"}:
            raise HTTPException(status_code=422, detail="Unknown watchlist kind")
        watchlist.kind = payload.kind

    session.commit()
    return _to_out(watchlist)


@router.delete("/watchlists/{watchlist_id}", status_code=204)
def delete(watchlist_id: int, session: Session = Depends(get_session)) -> None:
    watchlist = _get_or_404(session, watchlist_id)
    session.delete(watchlist)
    session.commit()


@router.post("/watchlists/{watchlist_id}/items", response_model=WatchlistOut, status_code=201)
def add_asset(
    watchlist_id: int, payload: WatchlistItemCreate, session: Session = Depends(get_session)
) -> WatchlistOut:
    """Add an asset. Re-adding updates the note rather than erroring --
    the repository is idempotent by design.
    """
    watchlist = _get_or_404(session, watchlist_id)
    asset = get_asset_or_404(session, payload.ticker)
    add_item(session, watchlist, asset, note=payload.note)
    session.commit()
    return _to_out(watchlist)


@router.delete("/watchlists/{watchlist_id}/items/{asset_id}", status_code=204)
def remove_asset(
    watchlist_id: int, asset_id: int, session: Session = Depends(get_session)
) -> None:
    from models.asset import Asset

    watchlist = _get_or_404(session, watchlist_id)
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"No asset with id {asset_id}")
    if not remove_item(session, watchlist, asset):
        raise HTTPException(
            status_code=404, detail=f"Asset {asset.ticker} is not on this watchlist"
        )
    session.commit()
