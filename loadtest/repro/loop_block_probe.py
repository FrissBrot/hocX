"""Muster-Reproduktion: synchroner Pool-Checkout in einer reinen ASGI-Middleware (wie
MaintenanceMiddleware -> current_effective_state -> engine.connect) friert bei erschöpftem
Pool den Event-Loop des ganzen Workers ein. Pool absichtlich klein (2), pool_timeout 5 s."""
import asyncio, threading, time
import urllib.request, uvicorn
from fastapi import Depends, FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

engine = create_engine("postgresql+psycopg://postgres:probe@localhost:5432/postgres", pool_size=2, max_overflow=0, pool_timeout=5)
SessionLocal = sessionmaker(bind=engine)
_cache = {"t": 0.0}

def current_state():  # wie maintenance_service.current_effective_state (Cache 2 s)
    if time.monotonic() - _cache["t"] < 2.0:
        return
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    _cache["t"] = time.monotonic()

class StateMiddleware:
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            try: current_state()
            except Exception: pass   # wie dort: letzter Stand gilt weiter
        await self.app(scope, receive, send)

app = FastAPI()
app.add_middleware(StateMiddleware)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@app.get("/slow")
def slow(db=Depends(get_db)):          # z. B. Export/Import, der seine Session lange hält
    db.execute(text("SELECT pg_sleep(12)"))
    return {}

@app.get("/ping")
async def ping():                      # kein DB-Zugriff
    return {}

def serve():
    uvicorn.run(app, host="127.0.0.1", port=8099, log_level="warning")

def get(path):
    t = time.monotonic(); urllib.request.urlopen("http://127.0.0.1:8099" + path, timeout=60).read(); return time.monotonic() - t

def main():
    threading.Thread(target=serve, daemon=True).start()
    time.sleep(1.5)
    print(f"/ping ohne Last: {get('/ping'):.3f}s")
    slow = [threading.Thread(target=get, args=("/slow",)) for _ in range(2)]
    for th in slow: th.start()
    time.sleep(2.5)
    print("/ping bei erschoepftem Pool:", ", ".join(f"{get('/ping'):.2f}s" for _ in range(4)))
    for th in slow: th.join()

main()
