import importlib

from typer.testing import CliRunner

cli_module = importlib.import_module("cofer_u_pass.cli.app")


def test_root_version_option(monkeypatch):
    monkeypatch.setattr(cli_module, "_current_version", lambda: "1.0.5")
    result = CliRunner().invoke(cli_module.app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "1.0.5"


def test_chat_command_is_registered():
    result = CliRunner().invoke(cli_module.app, ["chat", "--help"])
    assert result.exit_code == 0
    assert "--profile" in result.stdout
    assert "--conversation-id" in result.stdout


def test_profile_models_command_is_registered():
    result = CliRunner().invoke(cli_module.app, ["profiles", "models", "--help"])
    assert result.exit_code == 0
    assert "--refresh" in result.stdout
    assert "--json" in result.stdout


async def test_chat_session_reuses_conversation_and_can_start_new(monkeypatch, capsys):
    from types import SimpleNamespace

    prompts = iter(["hello", "follow up", "/id", "/new", "fresh", "/exit"])
    monkeypatch.setattr(cli_module.typer, "prompt", lambda *args, **kwargs: next(prompts))

    calls = []

    class FakeService:
        async def profile_status(self, profile, verify=False):
            return SimpleNamespace(provider="chatgpt")

    async def fake_turn(service, protocol, *, profile, prompt, conversation_id):
        calls.append((prompt, conversation_id))
        if prompt == "hello":
            cid = "conversation-1"
        elif prompt == "follow up":
            cid = conversation_id
        else:
            cid = "conversation-2"
        current = SimpleNamespace(
            state=SimpleNamespace(value="completed"),
            conversation_id=cid,
            error_message=None,
            run_id=f"run-{len(calls)}",
        )
        result = SimpleNamespace(conversation_id=cid, markdown=f"answer:{prompt}", text=f"answer:{prompt}")
        return current, result

    monkeypatch.setattr(cli_module, "_run_chat_turn", fake_turn)
    await cli_module._chat_session(FakeService(), cli_module.Path("ask.yaml"), profile="p")

    assert calls == [
        ("hello", None),
        ("follow up", "conversation-1"),
        ("fresh", None),
    ]
    output = capsys.readouterr().out
    assert "Conversation: conversation-1" in output
    assert "answer:hello" in output
    assert "answer:follow up" in output
    assert "answer:fresh" in output
