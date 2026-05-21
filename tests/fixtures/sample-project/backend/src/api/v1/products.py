"""Products API — CRUD endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.src.models.product import ProductCreate, ProductResponse

router = APIRouter()


@router.get("/products")
def list_products(db: Session = Depends()) -> list[ProductResponse]:
    """Return all products."""
    return []


@router.post("/products")
def create_product(payload: ProductCreate, db: Session = Depends()) -> ProductResponse:
    """Create a new product."""
    return ProductResponse(id=1, name=payload.name)


@router.get("/products/{pid}")
def get_product(pid: int, db: Session = Depends()) -> ProductResponse:
    """Fetch a product by ID."""
    return ProductResponse(id=pid, name="x")
# new line
