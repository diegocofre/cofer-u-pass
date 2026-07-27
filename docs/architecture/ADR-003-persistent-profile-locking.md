# ADR-003 — OS lock plus SQLite lease

Status: Accepted

The profile-directory OS lock is authoritative for exclusion. SQLite stores a lease and heartbeat for diagnosis and observability. The design permits concurrent runs on different profiles while prohibiting simultaneous operation on one profile.
