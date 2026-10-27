"""Local delivery orchestration. Commands come from a trusted, user-owned manifest."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import signal
import struct
import subprocess
import sys
import tomllib
import uuid
import zlib

VERSION = "0.1.0"
SLUG = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
VARIABLE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")
RUN_ID = re.compile(r"[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}\Z")


class PipelineError(Exception):
    """An error safe to display without including command output or credentials."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def relative_path(value: str) -> bool:
    return (isinstance(value, str) and bool(value) and "\\" not in value
            and not PurePosixPath(value).is_absolute()
            and all(p not in (".", "..", "") for p in value.split("/")))


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def read_manifest(path: Path) -> tuple[dict, str]:
    try:
        raw = path.read_bytes()
        config = tomllib.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        raise PipelineError("Cannot read a valid TOML manifest.") from None
    if set(config) - {"schema", "name", "steps", "environment"}:
        raise PipelineError("Unknown manifest fields.")
    if type(config.get("schema")) is not int or config["schema"] != 1:
        raise PipelineError("Manifest schema must be 1.")
    if not isinstance(config.get("name"), str) or not SLUG.fullmatch(config["name"]):
        raise PipelineError("Pipeline name must be a lowercase slug.")
    env = config.get("environment", [])
    if not isinstance(env, list) or any(not isinstance(k, str) or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", k) for k in env):
        raise PipelineError("environment must list environment variable names, never values.")
    if any(k.startswith("PIPELINE_") for k in env) or len(env) != len(set(env)):
        raise PipelineError("Reserved or duplicate environment names.")
    steps = config.get("steps")
    if not isinstance(steps, list) or not steps:
        raise PipelineError("At least one command step is required.")
    seen = set()
    allowed = {"id", "command", "outputs", "check", "timeout", "minimum_tests", "bundle_id", "version", "build", "width", "height"}
    for step in steps:
        if not isinstance(step, dict) or set(step) - allowed:
            raise PipelineError("Unknown step fields.")
        key = step.get("id")
        if not isinstance(key, str) or not SLUG.fullmatch(key) or key in seen:
            raise PipelineError("Step IDs must be unique lowercase slugs.")
        command = step.get("command")
        if not isinstance(command, list) or not command or any(not isinstance(s, str) or not s or "\0" in s for s in command):
            raise PipelineError("command must be a nonempty argument array; shell strings are unsupported.")
        outputs = step.get("outputs")
        if not isinstance(outputs, list) or not outputs or any(not relative_path(p) for p in outputs) or len(outputs) != len(set(outputs)):
            raise PipelineError("Each step needs unique relative output paths inside its step directory.")
        check = step.get("check", "files")
        if check not in {"files", "xcresult", "screenshots", "archive"}:
            raise PipelineError("Unsupported artifact check.")
        options = {"files": set(), "xcresult": {"minimum_tests"}, "screenshots": {"width", "height"}, "archive": {"bundle_id", "version", "build"}}
        if set(step) & {"minimum_tests", "width", "height", "bundle_id", "version", "build"} - options[check]:
            raise PipelineError("Validator options do not match the selected check.")
        if not integer(step.get("timeout", 900), 1):
            raise PipelineError("Step timeout must be a positive integer.")
        if check in {"xcresult", "archive"} and len(outputs) != 1:
            raise PipelineError("xcresult and archive checks each require exactly one output.")
        if check == "xcresult" and not integer(step.get("minimum_tests", 1), 1):
            raise PipelineError("minimum_tests must be positive.")
        if check == "archive" and any(not isinstance(step.get(k), str) or not step[k] for k in ("bundle_id", "version", "build")):
            raise PipelineError("Archive checks require bundle_id, version and build strings.")
        if check == "screenshots":
            if any(k in step and not integer(step[k], 1) for k in ("width", "height")):
                raise PipelineError("Screenshot dimensions must be positive integers.")
        used = {m for arg in command for m in VARIABLE.findall(arg)}
        previous_vars = {"PIPELINE_STAGE_" + previous.upper().replace("-", "_") + "_DIR" for previous in seen}
        if used - set(env) - previous_vars - {"PIPELINE_PROJECT_DIR", "PIPELINE_STEP_DIR", "PIPELINE_PYTHON"}:
            raise PipelineError("A command references an undeclared environment variable.")
        seen.add(key)
    return config, digest(raw)


def git_output(project: Path, *args) -> bytes:
    try:
        result = subprocess.run(["git", "-C", str(project), *args], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        raise PipelineError("Git is unavailable or timed out.") from None
    if result.returncode:
        raise PipelineError("The project must be a Git working tree.")
    return result.stdout


def source_fingerprint(project: Path) -> str:
    root = Path(os.fsdecode(git_output(project, "rev-parse", "--show-toplevel").strip())).resolve()
    if root != project.resolve():
        raise PipelineError("Use the Git working-tree root as --project.")
    files = set(git_output(project, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0")) - {b""}
    h = hashlib.sha256()
    for raw in sorted(files):
        name = os.fsdecode(raw)
        if name == ".ios-pipeline" or name.startswith(".ios-pipeline/"):
            continue
        path = project / name
        if not relative_path(name) or path.is_symlink() or (path.exists() and not path.is_file()):
            raise PipelineError("Source fingerprinting does not support symlinks or submodules.")
        h.update(raw + b"\0")
        if path.exists():
            h.update(str(path.stat().st_mode & 0o777).encode() + b"\0")
            h.update(file_digest(path).encode())
        else:
            h.update(b"deleted")
    return h.hexdigest()


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def private_directory(path: Path):
    if path.is_symlink():
        raise PipelineError("Pipeline storage must not be a symlink.")
    path.mkdir(mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)


@contextmanager
def project_lock(project: Path):
    root = project / ".ios-pipeline"
    private_directory(root)
    fd = os.open(root / "lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PipelineError("Another pipeline is using this project.") from None
        yield root
    finally:
        os.close(fd)


def save_json(path: Path, value: dict):
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
    os.replace(tmp, path)


def artifact_inventory(directory: Path, outputs: list[str]) -> dict[str, str]:
    inventory = {}
    for name in outputs:
        root = directory / name
        for ancestor in (root, *root.parents):
            if ancestor == directory:
                break
            if ancestor.is_symlink():
                raise PipelineError("Artifact symlinks are unsupported.")
        if not root.exists():
            raise PipelineError("A declared output is missing.")
        paths = [root] if root.is_file() else sorted(root.rglob("*"))
        count = 0
        for p in paths:
            if p.is_symlink():
                raise PipelineError("Artifact symlinks are unsupported.")
            if p.is_file():
                if p == root and not p.stat().st_size:
                    raise PipelineError("A declared artifact contains an empty file.")
                inventory[p.relative_to(directory).as_posix()] = file_digest(p)
                count += 1
            elif not p.is_dir():
                raise PipelineError("Artifacts must be regular files or directories.")
        if not count:
            raise PipelineError("A declared output directory is empty.")
    return inventory


def validate_test_summary(summary: dict, minimum: int) -> dict:
    keys = ("totalTestCount", "passedTests", "failedTests", "skippedTests")
    if not isinstance(summary, dict) or any(not integer(summary.get(k)) for k in keys):
        raise PipelineError("Unrecognized xcresult summary; no test pass can be established.")
    total, passed, failed, skipped = (summary[k] for k in keys)
    expected = summary.get("expectedFailures", 0)
    if (not integer(expected) or expected or total < minimum or passed != total
            or failed or skipped or summary.get("result") != "Passed"):
        raise PipelineError("Tests are missing, skipped, failed or below minimum_tests.")
    return {k: summary[k] for k in keys}


def check_png(path: Path, width=None, height=None) -> dict:
    # Check container structure, dimensions and chunk checksums; visual review stays manual.
    with path.open("rb") as f:
        if f.read(8) != b"\x89PNG\r\n\x1a\n":
            raise PipelineError("Screenshot is not a PNG.")
        dimensions = None
        seen_data = False
        while True:
            header = f.read(8)
            if len(header) != 8:
                raise PipelineError("PNG is truncated.")
            size, kind = struct.unpack(">I4s", header)
            if size > 64 * 1024 * 1024:
                raise PipelineError("PNG chunk exceeds the supported size.")
            data, crc = f.read(size), f.read(4)
            if len(data) != size or len(crc) != 4 or struct.unpack(">I", crc)[0] != zlib.crc32(kind + data):
                raise PipelineError("PNG chunk checksum failed.")
            if dimensions is None:
                if kind != b"IHDR" or size != 13:
                    raise PipelineError("PNG has no valid header.")
                dimensions = struct.unpack(">II", data[:8])
                if not all(dimensions) or (width and dimensions[0] != width) or (height and dimensions[1] != height):
                    raise PipelineError("Screenshot dimensions do not match the manifest.")
            if kind == b"IDAT":
                seen_data = True
            if kind == b"IEND":
                if size or not seen_data or f.read(1):
                    raise PipelineError("PNG has an invalid ending.")
                return {"width": dimensions[0], "height": dimensions[1]}


def check_archive(path: Path, step: dict) -> dict:
    try:
        outer = plistlib.loads((path / "Info.plist").read_bytes())["ApplicationProperties"]
        app_path = outer["ApplicationPath"]
        if not relative_path(app_path):
            raise ValueError()
        app = path / "Products" / app_path / "Info.plist"
        inner = plistlib.loads(app.read_bytes())
        expected = {"CFBundleIdentifier": step["bundle_id"], "CFBundleShortVersionString": step["version"], "CFBundleVersion": step["build"]}
        if any(inner.get(k) != v or outer.get(k) != v for k, v in expected.items()):
            raise ValueError()
        return {"identity_matches_manifest": True}
    except (OSError, ValueError, TypeError, KeyError, plistlib.InvalidFileException):
        raise PipelineError("Archive identity does not match bundle_id, version and build.") from None


def validate_artifacts(step: dict, directory: Path) -> tuple[dict, dict]:
    inventory = artifact_inventory(directory, step["outputs"])
    check = step.get("check", "files")
    evidence = {}
    if check == "xcresult":
        try:
            result = subprocess.run(["xcrun", "xcresulttool", "get", "test-results", "summary", "--path", str(directory / step["outputs"][0]), "--compact"], capture_output=True, timeout=60)
            if result.returncode:
                raise ValueError()
            summary = json.loads(result.stdout)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            raise PipelineError("xcresulttool could not read the test bundle.") from None
        evidence = validate_test_summary(summary, step.get("minimum_tests", 1))
        # Recent Xcode versions materialize database.sqlite3 while reading a bundle.
        # Record the complete post-read bundle, including that file, rather than
        # excluding it from integrity checks or recording a stale pre-read hash.
        inventory = artifact_inventory(directory, step["outputs"])
    elif check == "screenshots":
        evidence = {name: check_png(directory / name, step.get("width"), step.get("height")) for name in step["outputs"]}
    elif check == "archive":
        evidence = check_archive(directory / step["outputs"][0], step)
    return inventory, evidence


def execute(argv: list[str], project: Path, environment: dict, log: Path, timeout: int):
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        try:
            process = subprocess.Popen(argv, cwd=project, env=environment, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        except OSError:
            raise PipelineError("Cannot start a stage command; check installed tools.") from None
        try:
            code = process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise PipelineError("Stage interrupted or timed out; child processes were stopped.") from None
        if code:
            raise PipelineError("Stage command failed; inspect its private command.log.")


def run_pipeline(config: dict, config_hash: str, project: Path, resume: str | None = None) -> dict:
    project = project.resolve()
    required = config.get("environment", [])
    if any(not os.environ.get(k) for k in required):
        raise PipelineError("A declared environment variable is missing or empty.")
    selected_env = {k: os.environ.get(k, "") for k in [*required, "PATH", "DEVELOPER_DIR"]}
    env_hash = digest(json.dumps(selected_env, sort_keys=True).encode())
    source = source_fingerprint(project)
    with project_lock(project) as root:
        runs = root / "runs"
        private_directory(runs)
        if resume:
            if not RUN_ID.fullmatch(resume):
                raise PipelineError("Invalid run ID.")
            run_dir = runs / resume
            if run_dir.is_symlink():
                raise PipelineError("Run storage must not be a symlink.")
            try:
                state = json.loads((run_dir / "report.json").read_text())
            except (OSError, ValueError):
                raise PipelineError("No readable run report found.") from None
            if (not isinstance(state, dict) or state.get("schema") != 1
                    or state.get("pipeline_version") != VERSION
                    or not isinstance(state.get("steps"), dict)
                    or any(not isinstance(v, dict) or v.get("status") not in {"running", "passed", "failed"}
                           for v in state["steps"].values())):
                raise PipelineError("Invalid or incompatible run report; start a new run.")
            if (state.get("config_sha256"), state.get("source_sha256"), state.get("environment_sha256")) != (config_hash, source, env_hash):
                raise PipelineError("Source, configuration or selected environment changed; start a new run.")
        else:
            resume = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
            run_dir = runs / resume
            private_directory(run_dir)
            state = {"schema": 1, "pipeline_version": VERSION, "run_id": resume, "name": config["name"], "config_sha256": config_hash, "source_sha256": source, "environment_sha256": env_hash, "steps": {}, "status": "running"}
        report = run_dir / "report.json"
        try:
            for step in config["steps"]:
                key = step["id"]
                previous = state["steps"].get(key)
                if previous and previous.get("status") == "passed":
                    attempt_name = previous.get("attempt", "")
                    if not isinstance(attempt_name, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}-[a-f0-9]{8}", attempt_name):
                        raise PipelineError("Run report contains an invalid attempt reference.")
                    old_dir = run_dir / attempt_name
                    if old_dir.is_symlink():
                        raise PipelineError("Attempt storage must not be a symlink.")
                    hashes = artifact_inventory(old_dir, step["outputs"])
                    if hashes != previous.get("artifacts"):
                        raise PipelineError("A completed stage artifact changed; start a new run.")
                    print(f"REUSED {key}")
                    continue
                if source_fingerprint(project) != source:
                    raise PipelineError("Project source changed during execution; start a new run.")
                attempt = key + "-" + uuid.uuid4().hex[:8]
                directory = run_dir / attempt
                private_directory(directory)
                state["status"] = "running"
                state["steps"][key] = {"status": "running", "attempt": attempt}
                save_json(report, state)
                env = dict(os.environ)
                env.update(PIPELINE_PROJECT_DIR=str(project), PIPELINE_STEP_DIR=str(directory), PIPELINE_PYTHON=sys.executable)
                for previous_step in config["steps"]:
                    previous_key = previous_step["id"]
                    if previous_key == key:
                        break
                    variable = "PIPELINE_STAGE_" + previous_key.upper().replace("-", "_") + "_DIR"
                    env[variable] = str(run_dir / state["steps"][previous_key]["attempt"])
                argv = [VARIABLE.sub(lambda m: env[m.group(1)], arg) for arg in step["command"]]
                execute(argv, project, env, directory / "command.log", step.get("timeout", 900))
                artifacts, evidence = validate_artifacts(step, directory)
                if source_fingerprint(project) != source:
                    raise PipelineError("Project source changed during execution; start a new run.")
                state["steps"][key].update(status="passed", artifacts=artifacts, evidence=evidence)
                save_json(report, state)
                print(f"PASSED {key}")
            if source_fingerprint(project) != source:
                raise PipelineError("Project source changed during execution; start a new run.")
            state["status"] = "ready_for_review"
            state.pop("error", None)
        except (PipelineError, OSError) as exc:
            state["status"] = "failed"
            state["error"] = str(exc) if isinstance(exc, PipelineError) else "Local file operation failed."
            for entry in state["steps"].values():
                if entry["status"] == "running":
                    entry["status"] = "failed"
            save_json(report, state)
            print(f"RUN {resume}")
            raise PipelineError(state["error"]) from None
        save_json(report, state)
        print(f"READY_FOR_REVIEW {resume}")
        print("Review the private report and artifacts before releasing.")
        return state


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("operation", choices=["plan", "run"])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--resume", metavar="RUN_ID")
    args = parser.parse_args(argv)
    try:
        config, sha = read_manifest(args.config)
        if args.operation == "plan":
            if args.resume:
                raise PipelineError("--resume is only valid with run.")
            for n, step in enumerate(config["steps"], 1):
                print(f"{n:02d} {step['id']} [{step.get('check', 'files')}]")
            print("Final state: ready_for_review. Commands are not executed by plan.")
        else:
            run_pipeline(config, sha, args.project, args.resume)
        return 0
    except (PipelineError, OSError) as exc:
        print(f"ERROR: {exc if isinstance(exc, PipelineError) else 'Local file operation failed.'}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
