from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import devices, github, health, sandbox

app = FastAPI(title="AutoPatch Engine", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health.router)
app.include_router(github.router)
app.include_router(devices.router)
app.include_router(sandbox.router)
