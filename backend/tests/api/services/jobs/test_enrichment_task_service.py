from pytest import fixture
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import TaskStatus
from api.repositories.enrichment_task import EnrichmentTaskRepository
from api.schemas.enrichment_tasks import EnrichmentTaskUpdate
from api.services.jobs.enrichment_task_service import EnrichmentTaskService


class TestEnrichmentTaskServiceClaim:
    @fixture
    def tasks(self, mocker):
        return mocker.AsyncMock(spec=EnrichmentTaskRepository)

    @fixture
    def session(self, mocker):
        return mocker.AsyncMock(spec=AsyncSession)

    async def test_moves_a_pending_task_to_in_progress(self, tasks, session):
        tasks.update_if_status.return_value = True

        claimed = await EnrichmentTaskService(tasks, session).claim(
            task_id=42, job_id=7
        )

        assert claimed is True
        tasks.update_if_status.assert_awaited_once_with(
            42,
            7,
            expected=TaskStatus.PENDING,
            changes=EnrichmentTaskUpdate(status=TaskStatus.IN_PROGRESS),
        )
        session.commit.assert_awaited_once()

    async def test_reports_a_task_that_could_not_be_claimed(self, tasks, session):
        tasks.update_if_status.return_value = False

        claimed = await EnrichmentTaskService(tasks, session).claim(
            task_id=42, job_id=7
        )

        assert claimed is False
