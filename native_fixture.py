"""Native CI acceptance using a newly generated, synthetic iOS app only.

Requires macOS, full Xcode, an available iOS Simulator, and XcodeGen.
This fixture builds an unsigned archive and never contacts App Store Connect.
"""
import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

import ios_pipeline


def export_screenshot(bundle, output):
    with tempfile.TemporaryDirectory(prefix="pipeline-attachments-") as folder:
        subprocess.run(["xcrun", "xcresulttool", "export", "attachments", "--path", bundle, "--output-path", folder], check=True)
        images = list(Path(folder).rglob("*.png"))
        if len(images) != 1:
            raise RuntimeError("Expected exactly one kept screenshot from the passing UI test")
        shutil.copyfile(images[0], output)


def run(work_dir=None):
    devices = json.loads(subprocess.check_output(["xcrun", "simctl", "list", "devices", "available", "--json"]))["devices"]
    candidates = [(runtime, d) for runtime, group in devices.items() if ".iOS-" in runtime for d in group if "iPhone" in d["name"] and d["isAvailable"]]
    if not candidates:
        raise RuntimeError("Native acceptance needs an installed iPhone Simulator")
    runtime, reference = candidates[-1]
    device = subprocess.check_output(["xcrun", "simctl", "create", "ios-pipeline-fixture-" + uuid.uuid4().hex[:8], reference["deviceTypeIdentifier"], runtime], text=True).strip()
    print("Created an isolated fixture simulator; existing simulators are unchanged.")
    if work_dir:
        work_dir.mkdir(parents=True, exist_ok=False)
    workspace = nullcontext(str(work_dir)) if work_dir else tempfile.TemporaryDirectory(prefix="ios-pipeline-native-")
    with workspace as folder:
        project = Path(folder)
        for directory in ("App", "Tests", "UITests"):
            (project / directory).mkdir()
        (project / "App/Fixture.swift").write_text('''import SwiftUI
@main struct Fixture: App {
    var body: some Scene {
        WindowGroup {
            VStack(spacing: 16) {
                Image(systemName: "checkmark.seal.fill").font(.largeTitle)
                Text("Pipeline fixture").font(.title)
                Text("Synthetic data only").accessibilityIdentifier("pipeline-ready")
            }.padding()
        }
    }
}
''')
        (project / "Tests/FixtureTests.swift").write_text('''import XCTest
final class FixtureTests: XCTestCase {
    func testSyntheticCalculation() { XCTAssertEqual(2 + 3, 5) }
}
''')
        (project / "UITests/FixtureUITests.swift").write_text('''import XCTest
final class FixtureUITests: XCTestCase {
    func testLaunchAndCapture() {
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.staticTexts["pipeline-ready"].waitForExistence(timeout: 20))
        let image = XCTAttachment(screenshot: app.screenshot())
        image.name = "launch-screen"
        image.lifetime = .keepAlways
        add(image)
    }
}
''')
        (project / "project.yml").write_text('''name: PipelineFixture
options:
  bundleIdPrefix: com.example
  deploymentTarget:
    iOS: "17.0"
settings:
  base:
    GENERATE_INFOPLIST_FILE: YES
    MARKETING_VERSION: "1.0"
    CURRENT_PROJECT_VERSION: "1"
    CODE_SIGNING_ALLOWED: NO
targets:
  PipelineFixture:
    type: application
    platform: iOS
    sources: [App]
    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: com.example.pipelinefixture
        INFOPLIST_KEY_UILaunchScreen_Generation: YES
  PipelineFixtureTests:
    type: bundle.unit-test
    platform: iOS
    sources: [Tests]
    dependencies:
      - target: PipelineFixture
  PipelineFixtureUITests:
    type: bundle.ui-testing
    platform: iOS
    sources: [UITests]
    dependencies:
      - target: PipelineFixture
schemes:
  PipelineFixture:
    build:
      targets:
        PipelineFixture: all
    test:
      targets: [PipelineFixtureTests, PipelineFixtureUITests]
''')
        (project / ".gitignore").write_text(".ios-pipeline/\nxcuserdata/\n*.xcuserstate\n")
        subprocess.run(["git", "init", "-q", folder], check=True)
        subprocess.run(["xcodegen", "generate", "--spec", str(project / "project.yml"), "--project", folder], check=True)
        config = {"schema": 1, "name": "native-ios-fixture", "steps": [
            {"id": "test", "command": ["xcodebuild", "-project", "PipelineFixture.xcodeproj", "-scheme", "PipelineFixture", "-destination", f"platform=iOS Simulator,id={device}", "-derivedDataPath", "${PIPELINE_STEP_DIR}/DerivedData", "-resultBundlePath", "${PIPELINE_STEP_DIR}/Tests.xcresult", "test"], "outputs": ["Tests.xcresult"], "check": "xcresult", "minimum_tests": 2, "timeout": 900},
            {"id": "screenshots", "command": [sys.executable, str(Path(__file__).resolve()), "export", "${PIPELINE_STAGE_TEST_DIR}/Tests.xcresult", "${PIPELINE_STEP_DIR}/launch.png"], "outputs": ["launch.png"], "check": "screenshots", "timeout": 120},
            {"id": "archive", "command": ["xcodebuild", "-project", "PipelineFixture.xcodeproj", "-scheme", "PipelineFixture", "-destination", "generic/platform=iOS", "-derivedDataPath", "${PIPELINE_STEP_DIR}/DerivedData", "-archivePath", "${PIPELINE_STEP_DIR}/Fixture.xcarchive", "archive"], "outputs": ["Fixture.xcarchive"], "check": "archive", "bundle_id": "com.example.pipelinefixture", "version": "1.0", "build": "1", "timeout": 600},
        ]}
        sha = ios_pipeline.digest(json.dumps(config, sort_keys=True).encode())
        try:
            state = ios_pipeline.run_pipeline(config, sha, project)
            resumed = ios_pipeline.run_pipeline(config, sha, project, state["run_id"])
            assert state["steps"] == resumed["steps"]
            print("NATIVE ACCEPTANCE: iOS tests, kept UI screenshot, unsigned archive identity, and resume passed.")
        except Exception:
            # All contents come from the synthetic fixture above, never a private app.
            for log in project.glob(".ios-pipeline/runs/*/*/command.log"):
                print(f"SYNTHETIC FIXTURE LOG ({log.parent.name}):")
                print(log.read_text(errors="replace")[-12000:])
            raise
        finally:
            subprocess.run(["xcrun", "simctl", "shutdown", device], capture_output=True)
            print("Fixture simulator shut down; no simulator data was erased.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "export":
        export_screenshot(sys.argv[2], sys.argv[3])
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--work-dir", type=Path, help="Preserve synthetic source and receipts in a NEW directory")
        run(parser.parse_args().work_dir)
