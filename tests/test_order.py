import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app import main


@pytest.fixture
def products():
    """Provide sample catalog products for order tests."""
    return {
        1: {"id": 1, "name": "Laptop", "description": "", "price": 50000, "stock": 4},
        2: {"id": 2, "name": "Mouse", "description": "", "price": 1000, "stock": 8},
    }


@pytest.fixture
def client(monkeypatch, products):
    """Create a test client with a fake Catalog Service dependency."""
    def fake_catalog_request(path, method="GET", body=None):
        """Return product data or reserve stock for mocked catalog calls."""
        if path.startswith("/products/") and method == "GET":
            product_id = int(path.split("/")[-1])
            if product_id in products:
                return products[product_id]
            raise AssertionError(f"Unexpected product id: {product_id}")

        if path.startswith("/products/") and path.endswith("/reserve") and method == "POST":
            product_id = int(path.split("/")[-2])
            products[product_id]["stock"] -= body["quantity"]
            return products[product_id]

        raise AssertionError(f"Unexpected request: {method} {path}")

    with TemporaryDirectory() as directory:
        monkeypatch.setattr(main, "catalog_request", fake_catalog_request)
        main.DATABASE_PATH = str(Path(directory) / "orders.db")
        main.initialize_database()
        yield TestClient(main.app)


def test_health_check(client):
    """Verify that the health endpoint returns service status."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "order-service"}


def test_create_order(client, products):
    """Verify that an order can be created for an available product."""
    response = client.post(
        "/orders",
        json={"customer_name": "Aditi", "items": [{"product_id": 1, "quantity": 2}]},
    )

    assert response.status_code == 201
    assert response.json()["total_amount"] == 100000
    assert response.json()["items"][0]["product_name"] == "Laptop"
    assert products[1]["stock"] == 2


def test_list_orders(client):
    """Verify that created orders appear in the order list."""
    client.post(
        "/orders",
        json={"customer_name": "Aditi", "items": [{"product_id": 1, "quantity": 1}]},
    )
    client.post(
        "/orders",
        json={"customer_name": "Rahul", "items": [{"product_id": 2, "quantity": 3}]},
    )

    response = client.get("/orders")

    assert response.status_code == 200
    assert len(response.json()) == 2
    assert response.json()[0]["customer_name"] == "Aditi"
    assert response.json()[1]["customer_name"] == "Rahul"


def test_get_order_by_id(client):
    """Verify that an existing order can be fetched by ID."""
    created = client.post(
        "/orders",
        json={"customer_name": "Aditi", "items": [{"product_id": 1, "quantity": 1}]},
    )
    order_id = created.json()["id"]

    response = client.get(f"/orders/{order_id}")

    assert response.status_code == 200
    assert response.json()["id"] == order_id


def test_create_order_with_multiple_items(client):
    """Verify that an order can contain multiple items."""
    response = client.post(
        "/orders",
        json={
            "customer_name": "Aditi",
            "items": [
                {"product_id": 1, "quantity": 1},
                {"product_id": 2, "quantity": 2},
            ],
        },
    )

    assert response.status_code == 201
    assert response.json()["total_amount"] == 52000
    assert len(response.json()["items"]) == 2


def test_get_missing_order_returns_404(client):
    """Verify that requesting a missing order returns 404."""
    response = client.get("/orders/999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Order not found"


def test_create_order_validation_error(client):
    """Verify that invalid order data returns a validation error."""
    response = client.post(
        "/orders",
        json={"customer_name": "A", "items": [{"product_id": 1, "quantity": 0}]},
    )

    assert response.status_code == 422


def test_create_order_with_not_enough_stock_returns_409(client):
    """Verify that ordering more than available stock returns a conflict."""
    response = client.post(
        "/orders",
        json={"customer_name": "Aditi", "items": [{"product_id": 1, "quantity": 10}]},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Not enough stock for product 1"


def test_create_order_stores_no_order_when_stock_is_insufficient(client):
    """Verify that failed orders are not saved."""
    client.post(
        "/orders",
        json={"customer_name": "Aditi", "items": [{"product_id": 1, "quantity": 10}]},
    )

    response = client.get("/orders")

    assert response.status_code == 200
    assert response.json() == []


def test_create_order_reserves_stock_for_all_items(client, products):
    """Verify that stock is reserved for every ordered item."""
    response = client.post(
        "/orders",
        json={
            "customer_name": "Aditi",
            "items": [
                {"product_id": 1, "quantity": 2},
                {"product_id": 2, "quantity": 3},
            ],
        },
    )

    assert response.status_code == 201
    assert products[1]["stock"] == 2
    assert products[2]["stock"] == 5
