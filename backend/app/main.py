from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, exports, files, protocol_elements, protocols, templates, todos, users
from app.core.config import settings
from app.services.file_service import FileService


@asynccontextmanager
async def lifespan(_: FastAPI):
    FileService().ensure_storage()
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(templates.router, prefix="/api", tags=["templates"])
app.include_router(protocols.router, prefix="/api", tags=["protocols"])
app.include_router(protocol_elements.router, prefix="/api", tags=["protocol-elements"])
app.include_router(todos.router, prefix="/api", tags=["todos"])
app.include_router(files.router, prefix="/api", tags=["files"])
app.include_router(exports.router, prefix="/api", tags=["exports"])
