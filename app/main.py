import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


async def _startup() -> None:
    from app.documents.storage import ensure_bucket, make_s3_client
    ensure_bucket(make_s3_client())
    logger.info("S3 bucket ready")

    from app.admin.service import load_config_into_runtime
    from app.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        await load_config_into_runtime(db)
    logger.info("Runtime config loaded from DB")

    from app.db.models import Document, DocumentStatus
    from app.db.session import AsyncSessionLocal
    from app.documents.ingestion import ingest_document
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Document).where(Document.status == DocumentStatus.processing)
        )
        stuck = result.scalars().all()

    if stuck:
        logger.warning("Re-queuing %d document(s) stuck in 'processing'", len(stuck))
        for doc in stuck:
            asyncio.create_task(ingest_document(str(doc.id)))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("CogniFetch API starting up (env=%s)", settings.app_env)
    await _startup()
    yield
    logger.info("CogniFetch API shutting down")


app = FastAPI(title="CogniFetch", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - start) * 1000
    logger.info('"%s %s" %d  %.1fms', request.method, request.url.path, response.status_code, ms)
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


from app.auth.router import router as auth_router          # noqa: E402
from app.documents.router import router as documents_router  # noqa: E402
from app.chat.router import router as chat_router            # noqa: E402
from app.admin.router import router as admin_router          # noqa: E402

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(documents_router, prefix="/documents", tags=["documents"])
app.include_router(chat_router, prefix="/chat", tags=["chat"])
app.include_router(admin_router, prefix="/admin", tags=["admin"])


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok"}
