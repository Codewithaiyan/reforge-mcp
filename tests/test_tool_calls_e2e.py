"""Call the installed stdio server with the real MCP SDK, including its validation."""

import asyncio
import json
import os
import sys
import sysconfig
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
import git
import pytest
from jsonschema import Draft202012Validator
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

TOOL_NAMES = {
    "scan_repo",
    "get_chunk",
    "get_health_score",
    "write_fix",
    "git_commit",
    "infer_architecture",
    "read_memory",
    "write_memory",
    "score_risk",
    "generate_changelog",
}
SOURCE = "def add(a, b):\n    return a + b\n\n\ndef unused():\n    return 7\n"
GOOD_DIFF = "@@ -2 +2 @@\n-    return a + b\n+    return sum((a, b))\n"
BAD_FIX = "@@ -2 +2 @@\n-    return a + b\n+    return a - b\n"


@pytest.fixture(params=["\n", "\r\n"], ids=["lf", "crlf"])
def project(tmp_path, request):
    # Spaces, a nested path and a mixed-case name expose accidental path assumptions.
    root = tmp_path / "project with spaces"
    source = root / "src" / "Calc.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(SOURCE.replace("\n", request.param).encode("utf-8"))
    (root / "check.py").write_text(
        "from src.Calc import add\nassert add(2, 2) == 4\n",
        encoding="utf-8",
    )
    (root / ".gitignore").write_text(
        "reforge-state.json\n.reforge*\nreforge-state.json.bak.*\n"
        "REFORGE_CHANGES.md\n__pycache__/\n",
        encoding="utf-8",
    )
    (root / "reforge.toml").write_text(
        "[fix]\nsession_budget = 2\nconfirm_every = 1\n",
        encoding="utf-8",
    )
    repo = git.Repo.init(root)
    with repo.config_writer() as config:
        config.set_value("user", "name", "MCP Protocol Test")
        config.set_value("user", "email", "mcp-test@example.com")
        config.set_value("core", "autocrlf", "false")
        config.set_value("commit", "gpgsign", "false")
    repo.index.add(["src/Calc.py", "check.py", ".gitignore", "reforge.toml"])
    repo.index.commit("initial fixture")
    return root


@asynccontextmanager
async def server(root):
    executable = Path(sysconfig.get_path("scripts")) / (
        "reforge-mcp.exe" if os.name == "nt" else "reforge-mcp"
    )
    assert executable.is_file(), "Install the project before running protocol tests"
    environment = dict(os.environ)
    environment["PATH"] = (
        str(Path(sys.executable).parent) + os.pathsep + environment.get("PATH", "")
    )
    # Tests must execute freshly patched source even if two edits share an mtime.
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    parameters = StdioServerParameters(
        command=str(executable),
        cwd=str(root),
        env=environment,
    )
    with anyio.fail_after(60):
        async with (
            stdio_client(parameters) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tools = {tool.name: tool for tool in (await session.list_tools()).tools}
            assert set(tools) == TOOL_NAMES
            called = set()

            async def call(name, **arguments):
                # ClientSession.call_tool itself validates outputSchema for non-error results.
                result = await session.call_tool(name, arguments)
                assert not result.isError, (name, result.content)
                assert isinstance(result.structuredContent, dict), name
                Draft202012Validator(tools[name].outputSchema).validate(
                    result.structuredContent
                )
                assert len(result.content) == 1
                assert json.loads(result.content[0].text) == result.structuredContent
                called.add(name)
                return result.structuredContent

            yield call, called, session


def test_all_ten_tools_over_stdio(project):
    async def check():
        root = str(project)
        source = project / "src" / "Calc.py"
        original = source.read_bytes()
        async with server(project) as (call, called, _session):
            scan = await call("scan_repo", root_path=root)
            assert scan["summary"]["total_files"] == 2
            assert scan["summary"]["parse_failures"] == 0
            chunk = await call(
                "get_chunk",
                file_path=str(source),
                repo_root=root,
                start_line=1,
                end_line=2,
            )
            assert chunk["source"] == "def add(a, b):\n    return a + b"
            written = await call(
                "write_memory",
                key="pending_fixes",
                value=["review Calc.py"],
                repo_path=root,
            )
            assert written["success"] is True
            memory = await call("read_memory", key="pending_fixes", repo_path=root)
            assert memory["value"] == ["review Calc.py"]
            architecture = await call("infer_architecture", repo_path=root)
            state = json.loads(
                (project / "reforge-state.json").read_text(encoding="utf-8")
            )
            assert state["architecture_hypothesis"] == architecture
            risk = await call(
                "score_risk", symbol="add", file="src/Calc.py", repo_path=root
            )
            assert risk["basis"] == "symbol"
            assert "check.py" in risk["referenced_by"]
            health = await call("get_health_score", repo_path=root)
            assert health["coverage"] == 1.0
            assert isinstance(health["score"], (int, float))
            fixed = await call(
                "write_fix",
                file_path=str(source),
                repo_root=root,
                diff_str=GOOD_DIFF,
                test_command="python check.py",
                allowed_test_commands=["python"],
            )
            assert fixed["success"] is True
            assert fixed["test_output"] == ""
            assert fixed["backup"] is None
            assert source.read_bytes() == original.replace(b"a + b", b"sum((a, b))")
            committed = await call(
                "git_commit",
                repo_path=root,
                files=["src/Calc.py"],
                branch="cleanup",
                create_branch=True,
            )
            assert committed["success"] is True
            assert committed["branch"] == "cleanup"
            assert committed["commit_hash"] == git.Repo(project).head.commit.hexsha
            changelog = await call("generate_changelog", repo_path=root)
            assert changelog == {
                "success": True,
                "path": str(project / "REFORGE_CHANGES.md"),
            }
            assert (project / "REFORGE_CHANGES.md").is_file()
            assert called == TOOL_NAMES

    asyncio.run(check())


def test_edge_cases_over_stdio(project):
    async def check():
        root = str(project)
        source = project / "src" / "Calc.py"
        original = source.read_bytes()
        missing = str(project / "nonexistent")
        async with server(project) as (call, _called, session):
            scan = await call("scan_repo", root_path=missing)
            assert scan["error"] == f"Repository path does not exist: '{missing}'"
            file_scan = await call("scan_repo", root_path=str(source))
            assert file_scan["error"] == f"Repository path is not a directory: '{source}'"
            chunk = await call(
                "get_chunk",
                file_path=str(source),
                repo_root=root,
                start_line=999,
                end_line=1000,
            )
            assert chunk["source"] == "    return 7"
            assert chunk["start_line"] == chunk["end_line"] == chunk["total_lines"]
            inverted = await call(
                "get_chunk",
                file_path=str(source),
                repo_root=root,
                start_line=2,
                end_line=-1,
            )
            assert inverted["source"] == "    return a + b"
            unreadable = await call("get_chunk", file_path=missing, repo_root=root)
            assert set(unreadable) == {"error"}
            assert unreadable["error"].startswith("Not a file: ")
            memory = await call("read_memory", key="unknown-key", repo_path=root)
            assert memory == {"key": "unknown-key", "value": None, "found": False}
            risk = await call(
                "score_risk",
                symbol="unknown_symbol",
                file="src/Calc.py",
                repo_path=root,
            )
            assert risk["basis"] == "symbol"
            assert risk["referenced_by"] == []
            malformed = await call(
                "write_fix",
                file_path=str(source),
                repo_root=root,
                diff_str="not a unified diff\n",
            )
            assert malformed == {
                "success": False,
                "test_output": None,
                "error": "Failed to apply diff — verify the diff is valid and matches the file content",
                "rolled_back": True,
            }
            assert source.read_bytes() == original
            failed = await call(
                "write_fix",
                file_path=str(source),
                repo_root=root,
                diff_str=BAD_FIX,
                test_command="python check.py",
                allowed_test_commands=["python"],
            )
            assert failed["success"] is False
            assert failed["rolled_back"] is True
            assert failed["error"] == "Tests failed — changes rolled back"
            assert "AssertionError" in failed["test_output"]
            assert source.read_bytes() == original
            blocked = await call(
                "write_fix",
                file_path=str(source),
                repo_root=root,
                diff_str=GOOD_DIFF,
                test_command="pytest; echo blocked",
            )
            assert blocked["success"] is False
            assert blocked["rolled_back"] is False
            assert "Command injection blocked" in blocked["error"]
            assert source.read_bytes() == original
            no_files = await call("git_commit", repo_path=root, files=[])
            assert no_files["success"] is False
            assert (
                no_files["error"]
                == "No files given: list the files this commit should contain."
            )
            no_branch = await call(
                "git_commit",
                repo_path=root,
                files=["src/Calc.py"],
                branch="nonexistent",
            )
            assert no_branch["success"] is False
            assert no_branch["error"].startswith("Cannot checkout branch ")
            repo = git.Repo(project)
            before = repo.head.commit
            empty = await call("git_commit", repo_path=root, files=["src/Calc.py"])
            assert empty["success"] is False
            assert empty["error"] == "Nothing to commit: staged files match HEAD."
            assert repo.head.commit.hexsha == before.hexsha
            fixed = await call(
                "write_fix", file_path=str(source), repo_root=root, diff_str=GOOD_DIFF
            )
            assert fixed["success"] is True
            committed = await call("git_commit", repo_path=root, files=["src/Calc.py"])
            assert committed["success"] is True
            assert repo.head.commit.parents[0].hexsha == before.hexsha
            checkpoint = await call("git_commit", repo_path=root, files=["src/Calc.py"])
            assert checkpoint["needs_confirmation"] is True
            assert checkpoint["error"] is None
            still_empty = await call(
                "git_commit", repo_path=root, files=["src/Calc.py"], confirmed=True
            )
            assert still_empty["success"] is False
            assert still_empty["error"] == "Nothing to commit: staged files match HEAD."
            second_fix = await call(
                "write_fix", file_path=str(source), repo_root=root,
                diff_str="@@ -6 +6 @@\n-    return 7\n+    return 8\n",
            )
            assert second_fix["success"] is True
            confirmed = await call(
                "git_commit", repo_path=root, files=["src/Calc.py"], confirmed=True
            )
            assert confirmed["success"] is True
            budget = await call(
                "git_commit", repo_path=root, files=["src/Calc.py"], confirmed=True
            )
            assert budget["success"] is False
            assert (
                budget["error"]
                == "Session budget exceeded: 2/2 fixes used. Start a new session to continue."
            )
            unwritable = await call(
                "write_memory", key="key", value=None, repo_path=missing
            )
            assert unwritable["success"] is False
            assert isinstance(unwritable["error"], str)
            changelog = await call("generate_changelog", repo_path=missing)
            assert changelog == {
                "success": False,
                "path": str(Path(missing) / "REFORGE_CHANGES.md"),
                "error": f"Could not write '{Path(missing) / 'REFORGE_CHANGES.md'}'",
            }
            empty_root = project / "empty"
            empty_root.mkdir()
            health = await call("get_health_score", repo_path=str(empty_root))
            assert health["score"] is None
            assert health["coverage"] == 0
            assert "caveat" in health
            # These wrappers raise on state-save failure today. MCP marks them as
            # execution errors, which the SDK deliberately does not schema-validate.
            for name in ("infer_architecture", "get_health_score"):
                failure = await session.call_tool(name, {"repo_path": missing})
                assert failure.isError
                assert failure.structuredContent is None
                assert "reforge-state.tmp" in failure.content[0].text

    asyncio.run(check())
