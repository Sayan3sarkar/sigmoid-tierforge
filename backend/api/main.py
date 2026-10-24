from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from logging import getLogger
from time import monotonic

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.dependencies.aws.sqs import SQSClient
from api.dependencies.db_session import DBSession
from api.exceptions import register_exception_handlers
from api.routes import api_router
from config import Config, cfg, configure_logging

logger = getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(cfg.log_level)
    app.state.started_at = monotonic()
    DBSession.create()
    # The SQS client is used by uploads to queue enrichment events. No startup
    # queue check here: uploads fail with 503 if SQS is down; everything else works.
    async with SQSClient.connect(cfg):
        logger.info("%s started (%s)", cfg.app_name, cfg.environment)
        yield
    await DBSession.close()
    logger.info("%s stopped", cfg.app_name)


def create_app(config: Config = cfg) -> FastAPI:
    app = FastAPI(title=config.app_name, lifespan=lifespan)
    # Lets a browser frontend on another origin call the API. No credentials
    # (cookies or auth headers) are involved, so "*" is a valid default.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
