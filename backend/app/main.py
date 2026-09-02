from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import devices, github, health, observability, sandbox

app = FastAPI(title="AutoPatch Engine", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:3002",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health.router)
app.include_router(github.router)
app.include_router(devices.router)
app.include_router(sandbox.router)
app.include_router(observability.router)
