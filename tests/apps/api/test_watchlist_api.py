from __future__ import annotations

from fastapi.testclient import TestClient

import models


def test_list_watchlists_empty(client: TestClient) -> None:
    response = client.get("/watchlists")

    assert response.status_code == 200
    assert response.json() == []


def test_create_and_get_watchlist(client: TestClient) -> None:
    created = client.post(
        "/watchlists", json={"name": "AI", "kind": "theme", "description": "AI chain"}
    )

    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "AI"
    assert body["item_count"] == 0

    fetched = client.get(f"/watchlists/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["description"] == "AI chain"


def test_duplicate_watchlist_name_conflicts(client: TestClient) -> None:
    client.post("/watchlists", json={"name": "AI"})

    duplicate = client.post("/watchlists", json={"name": "AI"})

    assert duplicate.status_code == 409


def test_invalid_kind_is_rejected(client: TestClient) -> None:
    response = client.post("/watchlists", json={"name": "X", "kind": "nonsense"})

    assert response.status_code == 422


def test_unknown_watchlist_id_is_404(client: TestClient) -> None:
    assert client.get("/watchlists/999999").status_code == 404


def test_filter_by_kind(client: TestClient) -> None:
    client.post("/watchlists", json={"name": "AI", "kind": "theme"})
    client.post("/watchlists", json={"name": "Banking", "kind": "sector"})

    response = client.get("/watchlists", params={"kind": "theme"})

    assert [w["name"] for w in response.json()] == ["AI"]


def test_update_watchlist(client: TestClient) -> None:
    created = client.post("/watchlists", json={"name": "AI"}).json()

    response = client.patch(
        f"/watchlists/{created['id']}", json={"description": "updated", "kind": "theme"}
    )

    assert response.status_code == 200
    assert response.json()["description"] == "updated"
    assert response.json()["kind"] == "theme"


def test_renaming_onto_an_existing_name_conflicts(client: TestClient) -> None:
    client.post("/watchlists", json={"name": "AI"})
    other = client.post("/watchlists", json={"name": "Banking"}).json()

    response = client.patch(f"/watchlists/{other['id']}", json={"name": "AI"})

    assert response.status_code == 409


def test_delete_watchlist(client: TestClient) -> None:
    created = client.post("/watchlists", json={"name": "AI"}).json()

    assert client.delete(f"/watchlists/{created['id']}").status_code == 204
    assert client.get(f"/watchlists/{created['id']}").status_code == 404


def test_add_and_remove_items(client: TestClient, seeded_asset: models.Asset) -> None:
    watchlist = client.post("/watchlists", json={"name": "AI"}).json()

    added = client.post(
        f"/watchlists/{watchlist['id']}/items",
        json={"ticker": "RELIANCE", "note": "refining"},
    )
    assert added.status_code == 201
    assert added.json()["item_count"] == 1
    assert added.json()["items"][0]["ticker"] == "RELIANCE"

    removed = client.delete(f"/watchlists/{watchlist['id']}/items/{seeded_asset.id}")
    assert removed.status_code == 204
    assert client.get(f"/watchlists/{watchlist['id']}").json()["item_count"] == 0


def test_adding_an_unknown_ticker_is_404(client: TestClient) -> None:
    watchlist = client.post("/watchlists", json={"name": "AI"}).json()

    response = client.post(
        f"/watchlists/{watchlist['id']}/items", json={"ticker": "NOSUCH"}
    )

    assert response.status_code == 404


def test_adding_a_duplicate_asset_updates_rather_than_duplicating(
    client: TestClient, seeded_asset: models.Asset
) -> None:
    watchlist = client.post("/watchlists", json={"name": "AI"}).json()
    client.post(f"/watchlists/{watchlist['id']}/items", json={"ticker": "RELIANCE"})

    response = client.post(
        f"/watchlists/{watchlist['id']}/items",
        json={"ticker": "RELIANCE", "note": "second"},
    )

    assert response.status_code == 201
    assert response.json()["item_count"] == 1
    assert response.json()["items"][0]["note"] == "second"


def test_removing_an_asset_not_on_the_list_is_404(
    client: TestClient, seeded_asset: models.Asset
) -> None:
    watchlist = client.post("/watchlists", json={"name": "AI"}).json()

    response = client.delete(f"/watchlists/{watchlist['id']}/items/{seeded_asset.id}")

    assert response.status_code == 404
