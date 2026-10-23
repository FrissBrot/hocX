"""Hält eine yield-Dependency (wie get_db) ihre Ressource bis zum Ende einer StreamingResponse?"""
import threading, time, urllib.request
import fastapi, uvicorn
from fastapi import Depends, FastAPI
from fastapi.responses import StreamingResponse
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

engine = create_engine("postgresql+psycopg://postgres:probe@localhost:5432/postgres", pool_size=5, max_overflow=0)
SessionLocal = sessionmaker(bind=engine)
log = []
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        log.append(("dependency_exit", time.monotonic())); db.close()

app = FastAPI()
@app.get("/download")
def download(db=Depends(get_db)):
    db.execute(text("SELECT 1"))            # wie Auth/Rechteprüfung vor dem Streamen
    def body():
        for _ in range(6):
            time.sleep(0.5); yield b"x" * 1024
        log.append(("stream_end", time.monotonic()))
    return StreamingResponse(body())

threading.Thread(target=lambda: uvicorn.run(app, host="127.0.0.1", port=8098, log_level="warning"), daemon=True).start()
time.sleep(1.5)
t0 = time.monotonic()
def poll():
    while time.monotonic() - t0 < 4:
        print(f"t={time.monotonic()-t0:4.1f}s ausgecheckte Pool-Verbindungen: {engine.pool.checkedout()}")
        time.sleep(0.75)
th = threading.Thread(target=poll); th.start()
urllib.request.urlopen("http://127.0.0.1:8098/download").read()
th.join()
print("FastAPI", fastapi.__version__, {k: round(v - t0, 2) for k, v in log})
