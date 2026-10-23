from alembic.command import check, downgrade, upgrade
from alembic.script import ScriptDirectory

from tests.temporary_database import TemporaryDatabase


class TestMigrations:
    """Runs against the test database, already migrated to head."""

    def test_models_match_the_migrations(self, test_database):
        # Raises if autogenerate would produce a new migration, i.e. a model
        # was changed without one.
        check(TemporaryDatabase.alembic_config())

    def test_every_migration_downgrades_and_upgrades_again(self, test_database):
        config = TemporaryDatabase.alembic_config()
        head = ScriptDirectory.from_config(config).get_current_head()

        downgrade(config, "base")
        upgrade(config, "head")

        assert (
            test_database.fetch_value("SELECT version_num FROM alembic_version") == head
        )
