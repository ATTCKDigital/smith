"""Billing service entrypoint."""

from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/charge")
def charge(amount: float):
    return {"charged": amount}
