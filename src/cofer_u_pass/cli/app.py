from __future__ import annotations

import asyncio
import json
from importlib.resources import as_file, files
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

import typer
import uvicorn

from cofer_u_pass.application.service import ApplicationService
from cofer_u_pass.config.settings import (
    default_config_path,
    load_config,
    sanitized_snapshot,
    setup_files,
    rotate_api_token,
)
from cofer_u_pass.domain.models import ConversationMode

app = typer.Typer(no_args_is_help=True, help="Cofer U Pass local automation engine")
profiles_app = typer.Typer(no_args_is_help=True, help="Manage persistent browser profiles")
config_app = typer.Typer(no_args_is_help=True, help="Inspect configuration")
diagnostics_app = typer.Typer(no_args_is_help=True, help="Inspect and export diagnostic evidence")
app.add_typer(profiles_app, name="profiles")
app.add_typer(config_app, name="config")
app.add_typer(diagnostics_app, name="diagnostics")


def _current_version() -> str:
    import importlib.metadata
    try:
        return importlib.metadata.version("cofer-u-pass")
    except importlib.metadata.PackageNotFoundError:
        from cofer_u_pass import __version__
        return __version__


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(_current_version())
        raise typer.Exit()


@app.callback()
def root_callback(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed Cofer U Pass version and exit.",
    ),
) -> None:
    del version


def arun(coro):
    return asyncio.run(coro)


def emit(value: Any, json_output: bool = False) -> None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if json_output:
        typer.echo(json.dumps(value, ensure_ascii=False, default=str))
    elif isinstance(value, (dict, list)):
        typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    else:
        typer.echo(str(value))


def parse_inputs(items: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            raise typer.BadParameter(f"input must be key=value: {item}")
        key, raw = item.split("=", 1)
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        result[key] = value
    return result


_TERMINAL_RUN_STATES = {
    "completed", "cancelled", "failed", "authentication_required", "recoverable", "outcome_unknown"
}


async def _wait_for_cli_run(
    service: ApplicationService,
    run_id: str,
    *,
    event_callback=None,
):
    """Wait for a run while preserving the executor cleanup barrier."""
    last = 0
    while True:
        events = await service.db.get_events(run_id, last)
        for event in events:
            last = event.sequence
            if event_callback is not None:
                event_callback(event)
        current = await service.get_run(run_id)
        if current.state.value in _TERMINAL_RUN_STATES:
            await service.wait_for_execution_cleanup(run_id)
            current = await service.get_run(run_id)
            result = await service.db.get_result(run_id)
            return current, result
        await asyncio.sleep(0.2)


async def _run_chat_turn(
    service: ApplicationService,
    protocol: Path,
    *,
    profile: str,
    prompt: str,
    conversation_id: str | None,
):
    mode = ConversationMode.CONTINUE if conversation_id else ConversationMode.NEW
    run = await service.create_run(
        protocol,
        profile_id=profile,
        inputs={"prompt": prompt},
        conversation_mode=mode,
        conversation_id=conversation_id,
    )
    current, result = await _wait_for_cli_run(service, run.run_id)
    return current, result


async def _chat_session(
    service: ApplicationService,
    protocol: Path,
    *,
    profile: str,
    initial_conversation_id: str | None = None,
) -> None:
    profile_record = await service.profile_status(profile, verify=False)
    conversation_id = initial_conversation_id

    typer.echo(f"Cofer U Pass · {profile_record.provider}")
    typer.echo(f"Profile: {profile}")
    if conversation_id:
        typer.echo(f"Conversation: {conversation_id}")
    typer.echo("Commands: /new  /id  /help  /exit")
    typer.echo()

    while True:
        try:
            message = typer.prompt("You", prompt_suffix="> ")
        except (EOFError, KeyboardInterrupt):
            typer.echo("\nBye.")
            return

        message = message.strip()
        if not message:
            continue
        command = message.lower()
        if command in {"/exit", "/quit", "/q"}:
            typer.echo("Bye.")
            return
        if command == "/help":
            typer.echo("/new  start a new provider conversation")
            typer.echo("/id   show the current Cofer U Pass conversation id")
            typer.echo("/exit leave chat")
            continue
        if command == "/id":
            typer.echo(f"Conversation: {conversation_id or '(not started yet)'}")
            continue
        if command == "/new":
            conversation_id = None
            typer.echo("New conversation selected. Your next message will create it.")
            continue
        if command.startswith("/"):
            typer.echo(f"Unknown command: {message}. Type /help.")
            continue

        typer.echo("Assistant> ", nl=False)
        current, result = await _run_chat_turn(
            service, protocol, profile=profile, prompt=message, conversation_id=conversation_id
        )
        if current.state.value == "completed" and result is not None:
            conversation_id = result.conversation_id or current.conversation_id or conversation_id
            rendered = result.markdown.strip() or result.text.strip()
            typer.echo(rendered)
            continue

        typer.echo()
        detail = current.error_message or "run did not complete"
        typer.echo(f"[{current.state.value}] {detail}")
        typer.echo(f"Run: {current.run_id}")
        if current.state.value == "authentication_required":
            typer.echo(f"Reauthenticate with: cofer-u-pass profiles authenticate {profile}")
        if current.state.value in {"outcome_unknown", "recoverable", "authentication_required"}:
            typer.echo("Chat stopped so the run can be resolved safely before another message is sent.")
            return


@app.command()
def setup(dry_run: bool = typer.Option(False, "--dry-run"), skip_browser: bool = typer.Option(False, help="Skip Chromium installation (advanced/offline use).")):
    """Create local configuration/data storage, initialize SQLite, and install managed Chromium."""
    changes = setup_files(dry_run=dry_run)
    cfg = load_config()
    if dry_run:
        emit({"dry_run": True, "changes": changes, "chromium": "would install" if not skip_browser else "skipped"})
        return
    async def work():
        service = ApplicationService(cfg)
        await service.start(execute_queued=False)
        ok, detail = await service.db.integrity_check()
        return ok, detail
    ok, detail = arun(work())
    if not skip_browser:
        proc = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)
        if proc.returncode != 0:
            raise typer.Exit(proc.returncode)
    emit({"status": "ok" if ok else "failed", "changes": changes, "sqlite": detail, "next": "Create a profile with: cofer-u-pass profiles create NAME --provider chatgpt"})


@app.command()
def doctor(json_output: bool = typer.Option(False, "--json"), run_id: str | None = typer.Option(None, help="Create a sanitized diagnostic package for a run.")):
    async def work():
        cfg = load_config()
        service = ApplicationService(cfg)
        await service.start(execute_queued=False)
        if run_id:
            run = await service.get_run(run_id)
            path = await service.doctor.capture_basic(run_id, run.error_class.value if run.error_class else "manual", run.error_message or "manual diagnostic capture")
            return {"package": path, "inventory": service.doctor.inventory(Path(path))}
        checks = await service.doctor.preventive()
        return {"ok": all(c["ok"] for c in checks), "checks": checks}
    result = arun(work())
    emit(result, json_output)
    if not result.get("ok", True):
        raise typer.Exit(1)


@app.command()
def serve(host: str | None = typer.Option(None), port: int | None = typer.Option(None)):
    """Run the loopback HTTP/SSE API in the foreground."""
    cfg = load_config(explicit={"api": {**({"host": host} if host else {}), **({"port": port} if port else {})}})
    if cfg.api.host not in {"127.0.0.1", "::1", "localhost"}:
        raise typer.BadParameter("v1 API can bind only to loopback")
    from cofer_u_pass.api.app import create_app
    uvicorn.run(create_app(cfg), host=cfg.api.host, port=cfg.api.port, log_level=cfg.log_level.lower())


@app.command("run")
def run_protocol(
    protocol: Path,
    profile: str = typer.Option(..., "--profile"),
    input_values: list[str] = typer.Option([], "--input", help="Protocol input as key=value; repeatable."),
    conversation_mode: ConversationMode = typer.Option(ConversationMode.NEW, "--conversation-mode"),
    conversation_id: str | None = typer.Option(None, "--conversation-id"),
    client_request_id: str | None = typer.Option(None, "--client-request-id"),
    json_output: bool = typer.Option(False, "--json"),
):
    async def work():
        service = ApplicationService(load_config())
        await service.start(execute_queued=True)
        run = await service.create_run(
            protocol, profile_id=profile, inputs=parse_inputs(input_values), conversation_mode=conversation_mode,
            conversation_id=conversation_id, client_request_id=client_request_id,
        )
        def on_event(event):
            if json_output:
                typer.echo(event.model_dump_json())
            elif event.type != "response.delta":
                typer.echo(f"[{event.sequence:04d}] {event.type}")

        current, result = await _wait_for_cli_run(service, run.run_id, event_callback=on_event)
        return {
            "run": current.model_dump(mode="json"),
            "result": result.model_dump(mode="json") if result else None,
        }
    emit(arun(work()), json_output)


@app.command()
def chat(
    profile: str = typer.Option(..., "--profile", help="Persistent provider profile to use."),
    conversation_id: str | None = typer.Option(
        None, "--conversation-id", help="Resume an existing Cofer U Pass conversation."
    ),
):
    """Open a clean interactive terminal chat backed by ordinary persisted runs."""
    resource = files("cofer_u_pass").joinpath("_bundled_examples/ask.yaml")
    with as_file(resource) as protocol_path:
        async def work():
            service = ApplicationService(load_config())
            await service.start(execute_queued=True)
            try:
                await _chat_session(
                    service, Path(protocol_path), profile=profile,
                    initial_conversation_id=conversation_id,
                )
            finally:
                await service.shutdown(cooperative=True)

        arun(work())


@app.command()
def worker(
    bridge: str = typer.Option("http://127.0.0.1:4011", "--bridge", help="Cofer One IA bridge control URL."),
    profile: list[str] = typer.Option([], "--profile", help="Profile exposed by this worker; repeatable. Defaults to all ready profiles."),
    token_env: str = typer.Option("COFER_U_PASS_BRIDGE_KEY", "--token-env", help="Environment variable containing the bridge key."),
    once: bool = typer.Option(False, "--once", help="Process at most one job, useful for diagnostics."),
):
    """Connect outward to Cofer One IA and execute restricted text/file jobs."""
    async def work():
        from cofer_u_pass.provider.worker import BridgeWorker, bridge_token_from_env
        service = ApplicationService(load_config())
        await service.start(execute_queued=True)
        try:
            selected = list(profile)
            if not selected:
                selected = [p.profile_id for p in await service.list_profiles() if p.status == "ready" and p.authenticated]
            if not selected:
                raise typer.BadParameter("no ready authenticated profiles; pass --profile or authenticate a profile first")
            for profile_id in selected:
                current = await service.profile_status(profile_id, verify=False)
                if current.status != "ready" or not current.authenticated:
                    raise typer.BadParameter(
                        f"profile {profile_id!r} is not ready/authenticated; authenticate or verify it before starting the worker"
                    )
            bridge_worker = BridgeWorker(
                service, bridge_url=bridge, token=bridge_token_from_env(token_env), profiles=selected
            )
            typer.echo(f"Worker {bridge_worker.worker_id} -> {bridge}; profiles: {', '.join(selected)}")
            await bridge_worker.run(once=once)
        finally:
            await service.shutdown(cooperative=True)

    arun(work())


@app.command()
def status(run_id: str, json_output: bool = typer.Option(False, "--json")):
    async def work():
        s = ApplicationService(load_config()); await s.start(execute_queued=False); return await s.get_run(run_id)
    emit(arun(work()), json_output)


@app.command()
def stream(run_id: str, after: int = typer.Option(0, help="Start after this persisted event sequence."), json_output: bool = typer.Option(False, "--json")):
    async def work():
        s = ApplicationService(load_config()); await s.start(execute_queued=False)
        seq = after
        terminal = {"completed", "cancelled", "failed", "authentication_required", "recoverable", "outcome_unknown"}
        while True:
            batch = await s.db.get_events(run_id, seq)
            for ev in batch:
                seq = ev.sequence
                emit(ev, json_output)
            run = await s.get_run(run_id)
            if run.state.value in terminal and not batch:
                return
            await asyncio.sleep(0.2)
    arun(work())


@app.command()
def cancel(run_id: str, json_output: bool = typer.Option(False, "--json")):
    async def work():
        s = ApplicationService(load_config()); await s.start(execute_queued=False); return await s.cancel_run(run_id)
    emit(arun(work()), json_output)


@app.command()
def resume(run_id: str, json_output: bool = typer.Option(False, "--json")):
    async def work():
        s = ApplicationService(load_config()); await s.start(execute_queued=False); return await s.resume_run(run_id)
    emit(arun(work()), json_output)


@app.command("resolve-outcome")
def resolve_outcome(run_id: str, action_id: str = typer.Option(..., "--action"), effect: str = typer.Option(..., help="occurred or not-occurred"), json_output: bool = typer.Option(False, "--json")):
    async def work():
        s = ApplicationService(load_config()); await s.start(execute_queued=False); return await s.resolve_outcome(run_id, action_id, effect=effect)
    emit(arun(work()), json_output)


@app.command("import-conversation")
def import_conversation(profile: str = typer.Option(..., "--profile"), url: str = typer.Argument(...)):
    async def work():
        s = ApplicationService(load_config()); await s.start(execute_queued=False); return await s.import_conversation(profile, url)
    emit({"conversation_id": arun(work())})


@profiles_app.command("create")
def profile_create(name: str, provider: str = typer.Option(..., "--provider"), json_output: bool = typer.Option(False, "--json")):
    async def work():
        s = ApplicationService(load_config()); await s.start(execute_queued=False); return await s.create_profile(name, provider)
    emit(arun(work()), json_output)


@profiles_app.command("authenticate")
def profile_authenticate(name: str, timeout: float = typer.Option(900, help="Seconds to wait for manual login recognition."), json_output: bool = typer.Option(False, "--json")):
    typer.echo("A visible managed Chromium window will open. Complete login/MFA/CAPTCHA manually; Cofer U Pass only recognizes the authenticated state.")
    async def work():
        from cofer_u_pass.provider.service import RestrictedProviderService

        s = ApplicationService(load_config())
        await s.start(execute_queued=False)
        profile = await s.authenticate_profile(name, timeout_seconds=timeout)
        adapter = s.registry.create(profile.provider)
        if "inference.model.discover" in adapter.capabilities:
            provider = RestrictedProviderService(s)
            try:
                await provider.refresh_profile_catalog(name)
            except Exception:
                # Authentication is authoritative and must remain successful even
                # if a provider UI change prevents catalog discovery. The failed
                # refresh is persisted and can be inspected/retried explicitly.
                pass
        return profile
    emit(arun(work()), json_output)


@profiles_app.command("status")
def profile_status(name: str, verify: bool = typer.Option(False, "--verify"), json_output: bool = typer.Option(False, "--json")):
    async def work():
        s = ApplicationService(load_config()); await s.start(execute_queued=False); return await s.profile_status(name, verify=verify)
    emit(arun(work()), json_output)


@profiles_app.command("list")
def profile_list(json_output: bool = typer.Option(False, "--json")):
    async def work():
        s = ApplicationService(load_config()); await s.start(execute_queued=False); return await s.list_profiles()
    emit([p.model_dump(mode="json") for p in arun(work())], json_output)


@profiles_app.command("models")
def profile_models(
    name: str,
    refresh: bool = typer.Option(False, "--refresh", help="Rediscover models from the authenticated provider web UI."),
    json_output: bool = typer.Option(False, "--json"),
):
    """Inspect or explicitly refresh the derived model catalog for one profile."""
    if refresh:
        typer.echo("Refreshing the provider model catalog may open a managed Chromium window.")

    async def work():
        from cofer_u_pass.provider.service import RestrictedProviderService

        s = ApplicationService(load_config())
        await s.start(execute_queued=False)
        provider = RestrictedProviderService(s)
        snapshot = await provider.refresh_profile_catalog(name) if refresh else await provider.profile_catalog(name)
        if snapshot is None:
            profile = await s.profile_status(name, verify=False)
            return {
                "profile_id": profile.profile_id,
                "provider": profile.provider,
                "models": [],
                "error": "model catalog has not been discovered; run with --refresh",
                "updated_at": None,
            }
        return snapshot.model_dump(mode="json")

    emit(arun(work()), json_output)


@config_app.command("paths")
def config_paths():
    cfg = load_config()
    emit({"config": str(default_config_path()), "data_root": str(cfg.data_path), "database": str(cfg.db_path), "profiles": str(cfg.profiles_path), "artifacts": str(cfg.artifacts_path), "evidence": str(cfg.evidence_path), "backups": str(cfg.backups_path)})


@config_app.command("validate")
def config_validate():
    cfg = load_config()
    emit({"status": "ok", "schema_version": cfg.schema_version})


@config_app.command("rotate-token")
def config_rotate_token():
    cfg = load_config()
    path = rotate_api_token(cfg)
    emit({"status": "rotated", "token_file": str(path), "next": "Restart cofer-u-pass serve before using the new token."})


@config_app.command("show")
def config_show(effective: bool = typer.Option(True, "--effective/--raw"), profile: str | None = typer.Option(None, "--profile"), json_output: bool = typer.Option(False, "--json")):
    cfg = load_config()
    data = sanitized_snapshot(cfg)
    if profile:
        data["selected_profile"] = profile
    emit(data, json_output)


@diagnostics_app.command("inventory")
def diagnostics_inventory(package_dir: Path):
    async def work():
        s = ApplicationService(load_config()); await s.start(execute_queued=False); return s.doctor.inventory(package_dir)
    emit(arun(work()))


@diagnostics_app.command("export")
def diagnostics_export(package_dir: Path, output: Path = typer.Option(..., "--output")):
    typer.echo("Export includes only the files shown by `cofer-u-pass diagnostics inventory`. Review that inventory before sharing the ZIP.")
    async def work():
        s = ApplicationService(load_config()); await s.start(execute_queued=False); return s.doctor.export(package_dir, output)
    emit({"zip": str(arun(work()))})


def _latest_version() -> str:
    with urllib.request.urlopen("https://pypi.org/pypi/cofer-u-pass/json", timeout=10) as response:
        return json.load(response)["info"]["version"]


@app.command("cleanup")
def cleanup(apply: bool = typer.Option(False, "--apply", help="Apply the displayed retention cleanup plan."), json_output: bool = typer.Option(False, "--json")):
    async def work():
        s = ApplicationService(load_config()); await s.start(execute_queued=False); return await s.cleanup(apply=apply)
    plan = arun(work())
    emit(plan, json_output)
    if not apply:
        typer.echo("Dry-run only. Re-run with --apply to perform this exact class of conservative cleanup.")


@app.command("update")
def update_command(check: bool = typer.Option(False, "--check", help="Only check whether a newer package exists.")):
    if check:
        latest = _latest_version()
        current = _current_version()
        emit({"current": current, "latest": latest, "update_available": latest != current})
        return

    async def preflight():
        s = ApplicationService(load_config()); await s.start(execute_queued=False)
        if await s.db.has_active_runs():
            raise RuntimeError("active runs exist; cancel or complete them before updating")
        ok, detail = await s.db.integrity_check()
        if not ok:
            raise RuntimeError(f"SQLite integrity failed: {detail}")
        backup = await s.db.create_backup(s.config.backups_path)
        return backup
    backup = arun(preflight())
    typer.echo(f"Database backup created: {backup}")
    if shutil.which("uv"):
        cmd = ["uv", "tool", "upgrade", "cofer-u-pass"]
    elif shutil.which("pipx"):
        cmd = ["pipx", "upgrade", "cofer-u-pass"]
    else:
        raise typer.BadParameter("Neither uv nor pipx was found. Install the desired pinned version explicitly.")
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        typer.echo(f"Update failed. Database backup remains at {backup}", err=True)
        raise typer.Exit(proc.returncode)
    typer.echo("Package manager update completed. Run `cofer-u-pass setup` and `cofer-u-pass doctor` before the next run.")


def main() -> None:
    app()
