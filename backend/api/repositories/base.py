from api.dependencies.db_session import DbSessionDep


class BaseRepository:
    """Base for repositories: holds the request's DB session, injected by FastAPI.

    Subclasses are used as dependencies directly, e.g.
    `StoreRepositoryDep = Annotated[StoreRepository, Depends()]`.
    """

    def __init__(self, session: DbSessionDep) -> None:
        self.session = session
