# ADR-001 — Shared application service

Status: Accepted

Python, CLI, and HTTP/SSE are façades over `ApplicationService`. No public interface may call Playwright or provider adapters directly. This prevents semantic drift and enables cross-interface contract testing.
