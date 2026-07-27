# Migration and rollback notes

v1.0.0 initializes SQLite schema version 1. There are no earlier supported schemas.

Before any future migration, Cofer U Pass must verify there are no active runs, run `PRAGMA integrity_check`, and create a timestamped SQLite backup under the configured backups directory. Package rollback is performed by reinstalling a pinned package version. If a future older version cannot read the current schema, restore its matching backup rather than attempting an uncertain reverse migration.
