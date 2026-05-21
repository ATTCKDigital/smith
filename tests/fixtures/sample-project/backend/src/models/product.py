"""Product domain model + Pydantic schemas."""

from pydantic import BaseModel


class ProductCreate(BaseModel):
    name: str
    price: float


class ProductResponse(BaseModel):
    id: int
    name: str


class Product:
    """SQLAlchemy-style product entity (stub)."""

    def __init__(self, name: str):
        self.name = name

    def save(self) -> None:
        pass

    def delete(self) -> None:
        pass
