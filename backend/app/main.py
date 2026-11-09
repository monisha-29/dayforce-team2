"""FastAPI application entrypoint for Timecard Exception Agent."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_v1_router

app = FastAPI(
    title="Timecard Exception Agent API",
    description="Backend API for finding timecard exceptions, generating policy-grounded proposals, validating fixes, and recording manager decisions.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
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
