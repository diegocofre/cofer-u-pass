def summarize_metadata(payload: dict) -> dict:
    """Example trusted hook. Install/import this module before referencing it."""
    return {"keys": sorted(payload), "count": len(payload)}
