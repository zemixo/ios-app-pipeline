import contextlib
import io
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import ios_pipeline as pipeline
from demo_fixture import png


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "source.txt").write_text("original")
        self.output = io.StringIO()
        self.stdout = contextlib.redirect_stdout(self.output)
        self.stdout.__enter__()

    def tearDown(self):
        self.stdout.__exit__(None, None, None)
        self.temp.cleanup()

    def step(self, key="build", body="(p/'artifact').write_text('payload')", **kwargs):
        return {"id": key, "command": [sys.executable, "-c", "import os,pathlib; p=pathlib.Path(os.environ['PIPELINE_STEP_DIR']); " + body], "outputs": ["artifact"], **kwargs}

    def run_config(self, steps, resume=None, **kwargs):
        config = {"schema": 1, "name": "fixture", "steps": steps, **kwargs}
        sha = pipeline.digest(json.dumps(config, sort_keys=True).encode())
        return pipeline.run_pipeline(config, sha, self.root, resume)

    def report(self):
        return json.loads(next((self.root / ".ios-pipeline/runs").glob("*/report.json")).read_text())

    def test_success_records_hashes_and_keeps_data_private(self):
        result = self.run_config([self.step()])
        self.assertEqual(result["status"], "ready_for_review")
        self.assertEqual(result["steps"]["build"]["artifacts"]["artifact"], pipeline.digest(b"payload"))
        path = self.root / ".ios-pipeline/runs" / result["run_id"] / "report.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(str(self.root), path.read_text())

    def test_failing_command_stops_downstream(self):
        with self.assertRaises(pipeline.PipelineError):
            self.run_config([self.step(body="raise SystemExit(2)"), self.step("later")])
        state = self.report()
        self.assertEqual(state["status"], "failed")
        self.assertNotIn("later", state["steps"])

    def test_zero_exit_without_output_fails(self):
        with self.assertRaisesRegex(pipeline.PipelineError, "missing"):
            self.run_config([self.step(body="pass")])

    def test_resume_reuses_verified_artifact(self):
        step = self.step()
        one = self.run_config([step])
        two = self.run_config([step], one["run_id"])
        self.assertEqual(one["steps"], two["steps"])
        self.assertIn("REUSED build", self.output.getvalue())

    def test_resume_rejects_modified_source(self):
        step = self.step()
        one = self.run_config([step])
        (self.root / "source.txt").write_text("changed")
        with self.assertRaisesRegex(pipeline.PipelineError, "changed"):
            self.run_config([step], one["run_id"])

    def test_resume_rejects_modified_artifact(self):
        step = self.step()
        one = self.run_config([step])
        (self.root / ".ios-pipeline/runs" / one["run_id"] / one["steps"]["build"]["attempt"] / "artifact").write_text("tampered")
        with self.assertRaisesRegex(pipeline.PipelineError, "artifact changed"):
            self.run_config([step], one["run_id"])

    def test_resume_rejects_changed_config(self):
        one = self.run_config([self.step()])
        with self.assertRaisesRegex(pipeline.PipelineError, "changed"):
            self.run_config([self.step(timeout=1)], one["run_id"])

    def test_resume_rejects_changed_environment(self):
        with patch.dict(os.environ, {"FIXTURE_VALUE": "one"}):
            one = self.run_config([self.step()], environment=["FIXTURE_VALUE"])
        with patch.dict(os.environ, {"FIXTURE_VALUE": "two"}):
            with self.assertRaisesRegex(pipeline.PipelineError, "changed"):
                self.run_config([self.step()], one["run_id"], environment=["FIXTURE_VALUE"])

    def test_failed_attempt_is_preserved_and_resume_uses_fresh_directory(self):
        # Use a stable command with a deliberately untracked, test-only external switch.
        step = self.step(body="(p/'artifact').write_text('partial'); exit(3 if os.environ.get('FIXTURE_FAIL') else 0)")
        with patch.dict(os.environ, {"FIXTURE_FAIL": "yes"}):
            with self.assertRaises(pipeline.PipelineError):
                self.run_config([step])
        one = self.report()
        with patch.dict(os.environ):
            os.environ.pop("FIXTURE_FAIL", None)
            two = self.run_config([step], one["run_id"])
        self.assertNotEqual(one["steps"]["build"]["attempt"], two["steps"]["build"]["attempt"])
        self.assertTrue((self.root / ".ios-pipeline/runs" / one["run_id"] / one["steps"]["build"]["attempt"]).is_dir())

    def test_command_mutating_source_cannot_pass(self):
        with self.assertRaisesRegex(pipeline.PipelineError, "source changed"):
            self.run_config([self.step(body="(p/'artifact').write_text('ok'); pathlib.Path('source.txt').write_text('mutated')")])

    def test_timeout_blocks_pipeline(self):
        with self.assertRaisesRegex(pipeline.PipelineError, "timed out"):
            self.run_config([self.step(body="import time; time.sleep(15)", timeout=1)])

    def test_command_output_does_not_reach_terminal_or_report(self):
        secret = "synthetic-sensitive-value"
        result = self.run_config([self.step(body=f"print('{secret}'); (p/'artifact').write_text('ok')")])
        self.assertNotIn(secret, self.output.getvalue())
        self.assertNotIn(secret, json.dumps(result))
        log = self.root / ".ios-pipeline/runs" / result["run_id"] / result["steps"]["build"]["attempt"] / "command.log"
        self.assertIn(secret, log.read_text())
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)

    def test_symlink_storage_and_outputs_rejected(self):
        with tempfile.TemporaryDirectory() as target:
            (self.root / ".ios-pipeline").symlink_to(target)
            with self.assertRaises(pipeline.PipelineError):
                self.run_config([self.step()])
            (self.root / ".ios-pipeline").unlink()
        with self.assertRaisesRegex(pipeline.PipelineError, "symlink"):
            self.run_config([self.step(body="(p/'artifact').symlink_to(pathlib.Path('source.txt').resolve())")])

    def test_concurrent_run_is_rejected(self):
        with pipeline.project_lock(self.root):
            with self.assertRaisesRegex(pipeline.PipelineError, "Another pipeline"):
                self.run_config([self.step()])

    def test_corrupt_report_fails_cleanly(self):
        step = self.step()
        one = self.run_config([step])
        report = self.root / ".ios-pipeline/runs" / one["run_id"] / "report.json"
        report.write_text('[]')
        with self.assertRaisesRegex(pipeline.PipelineError, "Invalid"):
            self.run_config([step], one["run_id"])

    def test_test_gate_rejects_zero_failed_skipped_unknown_and_boolean_counts(self):
        good = {"result": "Passed", "totalTestCount": 2, "passedTests": 2, "failedTests": 0, "skippedTests": 0}
        self.assertEqual(pipeline.validate_test_summary(good, 2)["passedTests"], 2)
        for delta in ({"totalTestCount": 0, "passedTests": 0}, {"failedTests": 1}, {"skippedTests": 1}, {"passedTests": True}, {"expectedFailures": 1}, {"result": "Unknown"}):
            with self.subTest(delta=delta), self.assertRaises(pipeline.PipelineError):
                pipeline.validate_test_summary(good | delta, 1)
        with self.assertRaises(pipeline.PipelineError):
            pipeline.validate_test_summary(good, 3)

    def test_png_integrity_and_dimensions(self):
        path = self.root / "image.png"
        path.write_bytes(png())
        self.assertEqual(pipeline.check_png(path, 16, 16), {"width": 16, "height": 16})
        with self.assertRaises(pipeline.PipelineError):
            pipeline.check_png(path, 17, 16)
        path.write_bytes(png()[:-4])
        with self.assertRaises(pipeline.PipelineError):
            pipeline.check_png(path)

    def test_xcresult_read_cache_is_part_of_recorded_evidence(self):
        bundle = self.root / "Tests.xcresult"
        bundle.mkdir()
        (bundle / "result.data").write_bytes(b"synthetic-result")
        summary = {"result": "Passed", "totalTestCount": 2, "passedTests": 2, "failedTests": 0, "skippedTests": 0}
        def read_summary(*args, **kwargs):
            (bundle / "database.sqlite3").write_bytes(b"synthetic-cache-created-by-reader")
            return SimpleNamespace(returncode=0, stdout=json.dumps(summary).encode())
        with patch.object(pipeline.subprocess, "run", side_effect=read_summary):
            inventory, evidence = pipeline.validate_artifacts({"check": "xcresult", "outputs": ["Tests.xcresult"]}, self.root)
        self.assertIn("Tests.xcresult/database.sqlite3", inventory)
        self.assertEqual(inventory, pipeline.artifact_inventory(self.root, ["Tests.xcresult"]))
        self.assertEqual(evidence["passedTests"], 2)

    def test_downstream_receives_verified_previous_artifact_directory(self):
        one = self.step()
        two = self.step("inspect", body="(p/'artifact').write_text(pathlib.Path(os.environ['PIPELINE_STAGE_BUILD_DIR'],'artifact').read_text())")
        result = self.run_config([one, two])
        self.assertEqual(result["steps"]["build"]["artifacts"], result["steps"]["inspect"]["artifacts"])

    def test_archive_checks_inner_and_outer_identity(self):
        path = self.root / "Demo.xcarchive"
        app = path / "Products/Applications/Demo.app"
        app.mkdir(parents=True)
        attrs = {"ApplicationPath": "Applications/Demo.app", "CFBundleIdentifier": "com.example.demo", "CFBundleShortVersionString": "1.0", "CFBundleVersion": "1"}
        (path / "Info.plist").write_bytes(plistlib.dumps({"ApplicationProperties": attrs}))
        (app / "Info.plist").write_bytes(plistlib.dumps(attrs))
        step = {"bundle_id": "com.example.demo", "version": "1.0", "build": "1"}
        self.assertTrue(pipeline.check_archive(path, step)["identity_matches_manifest"])
        (app / "Info.plist").write_bytes(plistlib.dumps(attrs | {"CFBundleVersion": "2"}))
        with self.assertRaises(pipeline.PipelineError):
            pipeline.check_archive(path, step)

    def test_manifest_rejects_unsafe_paths_unknown_fields_and_shell_string(self):
        base = 'schema=1\nname="fixture"\n[[steps]]\nid="build"\ncommand=["true"]\noutputs=["artifact"]\n'
        p = self.root / "config.toml"
        for bad in (base.replace('"artifact"', '"../escape"'), base.replace('["true"]', '"true"'), base + 'typo = 1\n', base.replace('schema=1', 'schema=true'), base.replace('"true"', '"${UNDECLARED}"')):
            p.write_text(bad)
            with self.subTest(bad=bad), self.assertRaises(pipeline.PipelineError):
                pipeline.read_manifest(p)

    def test_plan_does_not_create_state_or_execute_commands(self):
        p = self.root / "config.toml"
        p.write_text('schema=1\nname="fixture"\n[[steps]]\nid="build"\ncommand=["does-not-exist"]\noutputs=["artifact"]\n')
        self.assertEqual(pipeline.main(["plan", "--config", str(p), "--project", str(self.root)]), 0)
        self.assertFalse((self.root / ".ios-pipeline").exists())


if __name__ == "__main__":
    unittest.main()
