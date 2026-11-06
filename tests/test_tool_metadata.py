"""Check the MCP metadata and output schemas clients actually consume."""

import asyncio
import json
import os
import sys

import anyio
import git
import pytest
from jsonschema import Draft202012Validator
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from reforge_mcp import __version__
from reforge_mcp.server import mcp

PARAMETERS = {
    "scan_repo": ["root_path", "languages", "include_tests"],
    "get_chunk": ["file_path", "repo_root", "start_line", "end_line"],
    "write_fix": [
        "file_path",
        "diff_str",
        "repo_root",
        "test_command",
        "allowed_test_commands",
    ],
    "git_commit": [
        "repo_path",
        "files",
        "message",
        "branch",
        "create_branch",
        "confirmed",
    ],
    "read_memory": ["key", "repo_path"],
    "write_memory": ["key", "value", "repo_path"],
    "infer_architecture": ["repo_path"],
    "score_risk": ["symbol", "file", "repo_path"],
    "get_health_score": ["repo_path"],
    "generate_changelog": ["repo_path"],
}


@pytest.fixture
def tools():
    return {tool.name: tool for tool in asyncio.run(mcp.list_tools())}


def test_tool_discovery_has_descriptions_schemas_and_accurate_annotations(tools):
    assert set(tools) == set(PARAMETERS)
    read_only = {"scan_repo", "get_chunk", "read_memory", "score_risk"}
    destructive = {"write_fix", "git_commit"}
    for name, tool in tools.items():
        assert "Use when: " in tool.description, name
        exclusion = tool.description.split("Don't use when: ", 1)[1].splitlines()[0]
        assert any(
            f"use {sibling} instead" in exclusion
            for sibling in tools
            if sibling != name
        )
        assert "Returns " in tool.description, name
        properties = tool.parameters["properties"]
        assert list(properties) == PARAMETERS[name]
        assert all(parameter.get("description") for parameter in properties.values()), (
            name
        )
        assert tool.output_schema["type"] == "object", name
        Draft202012Validator.check_schema(tool.output_schema)
        hints = tool.annotations
        assert hints.readOnlyHint is (name in read_only), name
        assert hints.destructiveHint is (name in destructive), name
        assert hints.idempotentHint is (name in read_only), name
        assert hints.openWorldHint is (name in destructive), name


def _call(tools, name, **arguments):
    result = asyncio.run(tools[name].run(arguments))
    data = result.structured_content
    Draft202012Validator(tools[name].output_schema).validate(data)
    # Adding a schema must not wrap or replace the existing JSON text payload.
    assert len(result.content) == 1
    assert json.loads(result.content[0].text) == data
    return data


def test_success_results_conform_without_changing_payloads(tools, tmp_path):
    source = tmp_path / "app.py"
    source.write_text("def main():\n    return 1\n", encoding="utf-8")
    repo = git.Repo.init(tmp_path)
    with repo.config_writer() as config:
        config.set_value("user", "name", "Metadata Test")
        config.set_value("user", "email", "metadata@example.com")
    repo.index.add(["app.py"])
    repo.index.commit("initial")
    root = str(tmp_path)

    scan = _call(tools, "scan_repo", root_path=root)
    assert scan["summary"]["total_files"] == 1
    chunk = _call(
        tools,
        "get_chunk",
        file_path=str(source),
        repo_root=root,
        start_line=2,
        end_line=2,
    )
    assert chunk["source"] == "    return 1"
    memory = _call(tools, "read_memory", key="missing", repo_path=root)
    assert memory == {"key": "missing", "value": None, "found": False}
    written = _call(
        tools,
        "write_memory",
        key="pending_fixes",
        value=["review app.py"],
        repo_path=root,
    )
    assert written["success"] is True
    architecture = _call(tools, "infer_architecture", repo_path=root)
    saved = _call(tools, "read_memory", key="architecture_hypothesis", repo_path=root)
    assert saved["value"] == architecture
    assert (tmp_path / "reforge-state.json").is_file()
    risk = _call(tools, "score_risk", symbol="main", file="app.py", repo_path=root)
    assert risk["basis"] == "symbol"
    health = _call(tools, "get_health_score", repo_path=root)
    assert health["coverage"] == 1
    changelog = _call(tools, "generate_changelog", repo_path=root)
    assert changelog == {"success": True, "path": str(tmp_path / "REFORGE_CHANGES.md")}
    fixed = _call(
        tools,
        "write_fix",
        file_path=str(source),
        repo_root=root,
        diff_str="@@ -2 +2 @@\n-    return 1\n+    return 2\n",
    )
    assert fixed["success"] is True
    assert fixed["git_state"] == "clean"
    assert fixed["backup"] is None
    committed = _call(tools, "git_commit", repo_path=root, files=["app.py"])
    assert committed["success"] is True
    assert committed["commit_hash"] == repo.head.commit.hexsha


def test_error_and_null_results_conform(tools, tmp_path, monkeypatch):
    from reforge_mcp.utils.security import SecurityError

    root = str(tmp_path)

    def reject_path(*args):
        raise SecurityError("Invalid path")

    with monkeypatch.context() as patch:
        patch.setattr("reforge_mcp.tools.scan.validate_path", reject_path)
        scan = _call(tools, "scan_repo", root_path=root)
    assert "error" in scan
    assert "subprojects" not in scan
    chunk = _call(
        tools, "get_chunk", file_path=str(tmp_path / "missing.py"), repo_root=root
    )
    assert set(chunk) == {"error"}
    fixed = _call(
        tools,
        "write_fix",
        file_path=str(tmp_path.parent / "outside.py"),
        repo_root=root,
        diff_str="",
    )
    assert fixed["success"] is False
    assert "backup" not in fixed
    committed = _call(tools, "git_commit", repo_path=root, files=[])
    assert committed["success"] is False
    missing = str(tmp_path / "missing")
    written = _call(tools, "write_memory", key="key", value=None, repo_path=missing)
    assert written["success"] is False
    assert "error" in written
    changelog = _call(tools, "generate_changelog", repo_path=missing)
    assert changelog["success"] is False
    health = _call(tools, "get_health_score", repo_path=root)
    assert health["score"] is None
    assert "caveat" in health


def test_commit_checkpoint_result_conforms(tools, tmp_path):
    from reforge_mcp.tools.git import _fix_counts, _session_key

    root = str(tmp_path)
    key = _session_key(root)
    _fix_counts[key] = 5
    try:
        result = _call(tools, "git_commit", repo_path=root, files=["app.py"])
    finally:
        _fix_counts.pop(key, None)
    assert result["success"] is False
    assert result["needs_confirmation"] is True
    assert result["error"] is None


def test_stdio_client_discovers_ten_documented_tools(tmp_path):
    """Start the real entry point and inspect the MCP wire response, not just Python."""

    async def check():
        server = StdioServerParameters(
            command=sys.executable,
            args=["-c", "from reforge_mcp.server import main; main()"],
            cwd=str(tmp_path),
            env=dict(os.environ),
        )
        with anyio.fail_after(30):
            async with (
                stdio_client(server) as (read, write),
                ClientSession(read, write) as session,
            ):
                initialized = await session.initialize()
                assert initialized.serverInfo.version == __version__
                listed = await session.list_tools()
                assert {tool.name for tool in listed.tools} == set(PARAMETERS)
                for tool in listed.tools:
                    assert all(
                        p.get("description")
                        for p in tool.inputSchema["properties"].values()
                    ), tool.name
                    hints = tool.annotations.model_dump(exclude_none=True)
                    assert set(hints) >= {
                        "readOnlyHint",
                        "destructiveHint",
                        "idempotentHint",
                        "openWorldHint",
                    }
                    assert tool.outputSchema["type"] == "object"
                result = await session.call_tool(
                    "read_memory",
                    {
                        "key": "missing",
                        "repo_path": str(tmp_path),
                    },
                )
                assert not result.isError
                assert result.structuredContent == {
                    "key": "missing",
                    "value": None,
                    "found": False,
                }

    asyncio.run(check())
