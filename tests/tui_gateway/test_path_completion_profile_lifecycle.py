"""Advisory path completion belongs to the chat and never provisions a sandbox."""

from pathlib import Path

import tui_gateway.server as server
from tui_gateway import launch_profile_policy


def test_completion_routes_profiles_without_creating_sandboxes(tmp_path, monkeypatch):
    from agent import secret_scope
    from tools import terminal_tool

    launch = tmp_path / "launch"
    worker = tmp_path / "profiles" / "worker"
    workspace = tmp_path / "workspace"
    for path in (launch, worker, workspace):
        path.mkdir(parents=True)
    (launch / "config.yaml").write_text(
        "terminal:\n  backend: docker\n  container_persistent: false\n"
    )
    (worker / "config.yaml").write_text("terminal:\n  backend: local\n")
    (workspace / "worker-only.txt").write_text("worker")
    (launch / ".env").write_text("COMPLETION_LAUNCH_TOKEN=launch\n")
    (worker / ".env").write_text("COMPLETION_WORKER_TOKEN=worker\n")
    monkeypatch.setenv("COMPLETION_LAUNCH_TOKEN", "launch")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(launch))
    monkeypatch.setenv("TERMINAL_ENV", "docker")
    monkeypatch.setenv("TERMINAL_CONTAINER_PERSISTENT", "false")
    monkeypatch.setattr(server, "_hermes_home", launch)
    monkeypatch.setattr(server, "_served_profile_homes", set())
    monkeypatch.setattr(launch_profile_policy, "_snapshot", None)
    monkeypatch.setattr(secret_scope, "_MULTIPLEX_ACTIVE", False)
    monkeypatch.setattr(terminal_tool, "_active_environments", {})
    monkeypatch.setattr(terminal_tool, "_start_cleanup_thread", lambda: None)
    monkeypatch.setattr(server, "_cfg_cache", None)
    monkeypatch.setattr(server, "_cfg_path", None)
    monkeypatch.setitem(
        server._sessions,
        "launch",
        {"session_key": "launch", "profile_home": None, "cwd": str(workspace)},
    )
    monkeypatch.setitem(
        server._sessions,
        "worker",
        {"session_key": "worker", "profile_home": str(worker), "cwd": str(workspace)},
    )
    creations = []

    def create(*args, **kwargs):
        creations.append(kwargs)
        raise RuntimeError("Sandbox creation is not an advisory operation")

    monkeypatch.setattr(terminal_tool, "_create_configured_env", create)
    terminal_tool._ensure_terminal_env_bridged()
    launch_profile_policy.activate_multi_profile_hosting()
    before = dict(server.os.environ)
    replies = [
        server._methods["complete.path"](
            "r", {"session_id": sid, "word": "@file:", "cwd": str(workspace)}
        )
        for sid in ("launch", "worker", "launch")
    ]
    assert [item["text"] for item in replies[1]["result"]["items"]] == [
        "@file:worker-only.txt"
    ]
    assert replies[0]["result"]["items"] == replies[2]["result"]["items"] == []
    assert creations == []
    assert dict(server.os.environ) == before


def test_remote_completion_does_not_create_environment(monkeypatch):
    from tools import terminal_tool
    from tui_gateway.methods_complete import _backend_dir_entries

    monkeypatch.setenv("TERMINAL_ENV", "docker")
    monkeypatch.setattr(terminal_tool, "_active_environments", {})
    monkeypatch.setattr(terminal_tool, "_start_cleanup_thread", lambda: None)
    creations = []

    def create(*args, **kwargs):
        creations.append(kwargs)
        raise RuntimeError("cold sandbox")

    monkeypatch.setattr(terminal_tool, "_create_configured_env", create)
    assert _backend_dir_entries("/workspace", "cold-session") == []
    assert creations == []


def test_existing_remote_environment_still_lists(monkeypatch):
    from types import SimpleNamespace
    from tools import terminal_tool
    from tui_gateway.methods_complete import _backend_dir_entries

    monkeypatch.setenv("TERMINAL_ENV", "docker")
    monkeypatch.setattr(terminal_tool, "_start_cleanup_thread", lambda: None)
    calls = []

    def execute(command, **kwargs):
        calls.append(command)
        return {"output": "src/\nREADME.md\n", "exit_code": 0}

    env = SimpleNamespace(execute=execute)
    key = terminal_tool._resolve_container_task_id("warm-session")
    monkeypatch.setattr(terminal_tool, "_active_environments", {key: env})
    assert _backend_dir_entries("/workspace", "warm-session") == [
        ("README.md", False),
        ("src", True),
    ]
    assert len(calls) == 1


def test_unknown_session_cannot_list_launch_files(tmp_path):
    (tmp_path / "launch-secret.txt").write_text("launch")
    reply = server._methods["complete.path"](
        "r", {"session_id": "missing", "word": "@file:", "cwd": str(tmp_path)}
    )
    assert reply["result"]["items"] == []
