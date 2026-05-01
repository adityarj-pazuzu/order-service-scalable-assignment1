import json
import os
import sqlite3
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from contextlib import contextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field


DATABASE_PATH = os.getenv("DATABASE_PATH", "orders.db")
CATALOG_SERVICE_URL = os.getenv("CATALOG_SERVICE_URL", "http://localhost:8001")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Initialize the database when the FastAPI application starts."""
    initialize_database()
    yield


app = FastAPI(title="Order Service", version="1.0.0", lifespan=lifespan)


class OrderItemCreate(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0)


class OrderCreate(BaseModel):
    customer_name: str = Field(min_length=2, max_length=100)
    items: list[OrderItemCreate] = Field(min_length=1)


class OrderItem(BaseModel):
    product_id: int
    product_name: str
    quantity: int
    unit_price: float


class Order(BaseModel):
    id: int
    customer_name: str
    status: str
    total_amount: float
    items: list[OrderItem]


def get_connection() -> sqlite3.Connection:
    """Create a SQLite connection with rows accessible by column name."""
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def db_session():
    """Provide a database session and commit changes after successful use."""
    connection = get_connection()
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize_database() -> None:
    """Create the order tables if they do not already exist."""
    with db_session() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name TEXT NOT NULL,
                status TEXT NOT NULL,
                total_amount REAL NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                product_name TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders (id)
            )
            """
        )


def database_dependency():
    """Yield a database connection for FastAPI route handlers."""
    with db_session() as connection:
        yield connection


Database = Annotated[sqlite3.Connection, Depends(database_dependency)]


def catalog_request(path: str, method: str = "GET", body: dict | None = None) -> dict:
    """Send an HTTP request to the Catalog Service and return JSON data."""
    url = f"{CATALOG_SERVICE_URL}{path}"
    data = None
    headers = {"Content-Type": "application/json"}

    if body is not None:
        data = json.dumps(body).encode("utf-8")

    request = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8")
        raise HTTPException(status_code=error.code, detail=f"Catalog Service error: {detail}")
    except urllib.error.URLError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Catalog Service unavailable: {error.reason}",
        )


def order_from_database(order_id: int, database: sqlite3.Connection) -> Order | None:
    """Build an order response model from database records."""
    order_row = database.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order_row is None:
        return None

    item_rows = database.execute(
        "SELECT * FROM order_items WHERE order_id = ? ORDER BY id",
        (order_id,),
    ).fetchall()

    items = [
        OrderItem(
            product_id=row["product_id"],
            product_name=row["product_name"],
            quantity=row["quantity"],
            unit_price=row["unit_price"],
        )
        for row in item_rows
    ]

    return Order(
        id=order_row["id"],
        customer_name=order_row["customer_name"],
        status=order_row["status"],
        total_amount=order_row["total_amount"],
        items=items,
    )


@app.get("/health")
def health() -> dict[str, str]:
    """Return service health information."""
    return {"status": "ok", "service": "order-service"}


@app.post("/orders", response_model=Order, status_code=status.HTTP_201_CREATED)
def create_order(order: OrderCreate, database: Database) -> Order:
    """Create an order after checking and reserving catalog stock."""
    product_details = []

    for item in order.items:
        product = catalog_request(f"/products/{item.product_id}")
        if product["stock"] < item.quantity:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Not enough stock for product {item.product_id}",
            )
        product_details.append((item, product))

    total_amount = sum(item.quantity * product["price"] for item, product in product_details)

    for item, _product in product_details:
        catalog_request(
            f"/products/{item.product_id}/reserve",
            method="POST",
            body={"quantity": item.quantity},
        )

    cursor = database.execute(
        """
        INSERT INTO orders (customer_name, status, total_amount)
        VALUES (?, ?, ?)
        """,
        (order.customer_name, "CREATED", total_amount),
    )
    order_id = cursor.lastrowid

    for item, product in product_details:
        database.execute(
            """
            INSERT INTO order_items (order_id, product_id, product_name, quantity, unit_price)
            VALUES (?, ?, ?, ?, ?)
            """,
            (order_id, item.product_id, product["name"], item.quantity, product["price"]),
        )

    created_order = order_from_database(order_id, database)
    if created_order is None:
        raise HTTPException(status_code=500, detail="Order creation failed")
    return created_order


@app.get("/orders", response_model=list[Order])
def list_orders(database: Database) -> list[Order]:
    """Return all orders ordered by order ID."""
    rows = database.execute("SELECT id FROM orders ORDER BY id").fetchall()
    orders = [order_from_database(row["id"], database) for row in rows]
    return [order for order in orders if order is not None]


@app.get("/orders/{order_id}", response_model=Order)
def get_order(order_id: int, database: Database) -> Order:
    """Return a single order by ID."""
    order = order_from_database(order_id, database)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order
