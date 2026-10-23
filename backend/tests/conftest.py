from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

from tests.temporary_database import TemporaryDatabase

# Must run before anything imports `config`: the test settings win over .env,
# and DATABASE_URL is pointed at a fresh, uniquely named database.
load_dotenv(Path(__file__).parent / ".test.env", override=True)
TEST_DATABASE = TemporaryDatabase.use_for_tests()

from fastapi.testclient import TestClient  # noqa: E402
from pytest import fixture  # noqa: E402

from api.dependencies.aws.sqs import SQSClient  # noqa: E402
from api.main import create_app  # noqa: E402


@fixture(scope="session")
def test_database():
    """Creates and migrates the run's temporary database once; drops it at the end."""
    TEST_DATABASE.create()
    TEST_DATABASE.migrate()
    yield TEST_DATABASE
    TEST_DATABASE.drop()


@fixture
def sqs_client(mocker):
    """A mocked SQSClient handed out by SQSClient.connect() (no LocalStack needed).

    The fake connect() behaves like the real one: the client is the shared
    instance inside the block and is cleared on the way out.
    """
    client = mocker.AsyncMock(spec=SQSClient)

    @asynccontextmanager
    async def connect(cfg):
        SQSClient._instance = client
        try:
            yield client
        finally:
            SQSClient._instance = None

    mocker.patch.object(SQSClient, "connect", side_effect=connect)
    return client


@fixture
def app(test_database):
    application = create_app()
    yield application
    application.dependency_overrides.clear()


@fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client
