from fastapi import APIRouter

from app.api.v1 import auth, books, exercises, misc, progress, tutor, vocabulary

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(books.router)
api_router.include_router(exercises.router)
api_router.include_router(vocabulary.router)
api_router.include_router(tutor.router)
api_router.include_router(progress.router)
api_router.include_router(misc.router)
