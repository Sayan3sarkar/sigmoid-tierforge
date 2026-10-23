from pathlib import Path

from dotenv import load_dotenv

from tests.temporary_database import TemporaryDatabase

# Must run before anything imports `config`: the test settings win over .env,
# and DATABASE_URL is pointed at a fresh, uniquely named database.
load_dotenv(Path(__file__).parent / ".test.env", override=True)
TEST_DATABASE = TemporaryDatabase.use_for_tests()

from fastapi.testclient import TestClient  # noqa: E402
from pytest import fixture  # noqa: E402

from api.aws.sqs import SQSQueue  # noqa: E402
from api.main import create_app  # noqa: E402


@fixture(scope="session")
def test_database():
    """Creates the run's temporary database once, and drops it at the end."""
    TEST_DATABASE.create()
    yield TEST_DATABASE
    TEST_DATABASE.drop()


@fixture
def sqs_queue(mocker):
    """A mocked SQSQueue, also returned by SQSQueue.create (no LocalStack needed)."""
    queue = mocker.AsyncMock(spec=SQSQueue)
    queue.queue_url = "http://localhost:4566/000000000000/tierforge-enrichment-test"
    mocker.patch.object(
        SQSQueue, "create", new_callable=mocker.AsyncMock, return_value=queue
    )
    return queue


@fixture
def app(sqs_queue, test_database):
    application = create_app()
    yield application
    application.dependency_overrides.clear()


@fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client
