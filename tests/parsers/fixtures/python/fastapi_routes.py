from fastapi import APIRouter, FastAPI

app = FastAPI()
router = APIRouter()


@app.get("/")
def root():
    return {"ok": True}


@app.post("/items")
def create_item(name: str):
    return {"name": name}


@router.get("/users/{id}")
def get_user(id: int):
    """Fetch a user by id."""
    return {"id": id}


@router.patch("/users/{id}")
async def update_user(id: int, payload: dict):
    return {"id": id, **payload}


@router.delete("/users/{id}")
def delete_user(id: int):
    return None
