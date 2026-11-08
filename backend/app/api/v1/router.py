"""API v1 router aggregator."""

from fastapi import APIRouter

from app.api.v1.audit import router as audit_router
from app.api.v1.exceptions import router as exceptions_router
from app.api.v1.proposals import router as proposals_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(exceptions_router)
api_v1_router.include_router(proposals_router)
api_v1_router.include_router(audit_router)
