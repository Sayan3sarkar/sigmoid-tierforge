from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from logging import getLogger
from time import monotonic

from fastapi import FastAPI

from api.aws.sqs import SQSQueue
from api.dependencies.db_session import DBSession
from api.routes import api_router
from config import cfg, configure_logging

logger = getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(cfg.log_level)
    app.state.started_at = monotonic()
    DBSession.create()
    app.state.sqs_queue = await SQSQueue.create(cfg)
    logger.info("%s started (%s)", cfg.app_name, cfg.environment)
    try:
        yield
    finally:
        await app.state.sqs_queue.close()
        await DBSession.close()
        logger.info("%s stopped", cfg.app_name)


def create_app() -> FastAPI:
    app = FastAPI(title=cfg.app_name, lifespan=lifespan)
    app.include_router(api_router)
    return app


app = create_app()
