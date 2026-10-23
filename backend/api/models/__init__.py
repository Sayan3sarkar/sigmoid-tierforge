"""ORM models, shared by the API and the worker.

Keep this package free of FastAPI imports so the worker can use it.
Import every model module here so Alembic's autogenerate sees it.
"""

from api.models.base import Base

__all__ = ["Base"]
