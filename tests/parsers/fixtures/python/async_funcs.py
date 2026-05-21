import asyncio


async def fetch(url: str) -> str:
    """Fetch a URL asynchronously."""
    await asyncio.sleep(0.1)
    return url


async def stream(n: int = 10):
    for i in range(n):
        yield i
