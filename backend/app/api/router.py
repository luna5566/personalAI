from fastapi import APIRouter

from app.api.routes import (
    auth,
    chat,
    documents,
    health,
    jobs,
    organize,
    registration_invites,
    settings,
    tags,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router)
api_router.include_router(registration_invites.router)
api_router.include_router(documents.router)
api_router.include_router(chat.router)
api_router.include_router(organize.router)
api_router.include_router(jobs.router)
api_router.include_router(tags.router)
api_router.include_router(settings.router)
