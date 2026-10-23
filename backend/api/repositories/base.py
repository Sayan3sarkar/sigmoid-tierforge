from api.dependencies.db_session import DbSessionDep


class BaseRepository:
    """Base for repositories: holds the request's AsyncSession, injected by FastAPI.

    `DbSessionDep` makes FastAPI call `DBSession.session()`, which opens one
    AsyncSession per request from the shared engine created once at startup.
    Subclasses are used as dependencies directly, e.g.
    `StoreRepositoryDep = Annotated[StoreRepository, Depends()]`.

    Repositories never commit. They add, flush and update within the caller's
    transaction; the service that calls them decides when to commit.
    """

    def __init__(self, session: DbSessionDep) -> None:
        self.session = session
