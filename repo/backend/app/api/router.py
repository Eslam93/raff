"""All HTTP API routes. The app mounts this router at /api."""

from fastapi import APIRouter

from app.api.routers import (
    activity,
    auth,
    books,
    copies,
    copilot,
    dashboard,
    health,
    holds,
    isbn,
    loans,
    me,
    members,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(me.router)
api_router.include_router(dashboard.router)
api_router.include_router(books.router)
api_router.include_router(isbn.router)
api_router.include_router(copies.router)
api_router.include_router(members.router)
api_router.include_router(loans.router)
api_router.include_router(holds.router)
api_router.include_router(activity.router)
api_router.include_router(copilot.router)
