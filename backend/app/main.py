"""FastAPI application entrypoint for Timecard Exception Agent."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models as _models  # noqa: F401  (registers the tables)
from app.api.v1.router import api_v1_router
from app.config import settings
from app.database import Base, SessionLocal, engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Create tables on a fresh database and optionally load the demo dataset."""
    Base.metadata.create_all(bind=engine)
    if settings.SEED_ON_START:
        from app.models.exception import ExceptionModel
        from app.services.dataset_service import load_dataset_from_file

        with SessionLocal() as session:
            if session.query(ExceptionModel).count() == 0:
                result = load_dataset_from_file(session, settings.SEED_FILE)
                logger.info("Seeded demo data from %s: %s", settings.SEED_FILE, result)
    yield


app = FastAPI(
    title="Timecard Exception Agent API",
    description="Backend API for finding timecard exceptions, generating policy-grounded proposals, validating fixes, and recording manager decisions.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Enable CORS for frontend applications
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://localhost:80",
        "http://localhost:4010",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["Health"], summary="Health Check")
def health_check() -> dict[str, str]:
    """Health check endpoint confirming service readiness."""
    return {"status": "ok"}


# Include primary v1 API router
app.include_router(api_v1_router)
