import pytest

from cofer_u_pass.persistence.database import Database, SCHEMA_VERSION


@pytest.mark.asyncio
async def test_schema_initialization_and_backup(config):
    db = Database(config.db_path)
    await db.initialize()
    assert await db.schema_version() == SCHEMA_VERSION == 1
    backup = await db.create_backup(config.backups_path)
    assert backup.exists() and backup.stat().st_size > 0

@pytest.mark.asyncio
async def test_newer_schema_is_never_downgraded(config):
    import sqlite3
    config.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.db_path)
    conn.execute("CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO schema_meta(key,value) VALUES('schema_version','99')")
    conn.commit(); conn.close()
    db = Database(config.db_path)
    with pytest.raises(RuntimeError, match="newer than supported"):
        await db.initialize()
    conn = sqlite3.connect(config.db_path)
    value = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0]
    conn.close()
    assert value == "99"
