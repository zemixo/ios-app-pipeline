# iOS App Pipeline

![iOS App Pipeline — Zemixo pixel workshop](banner.svg)

[![CI](https://github.com/zemixo/ios-app-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/zemixo/ios-app-pipeline/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-80c9e8)](pyproject.toml)
[![MIT](https://img.shields.io/badge/license-MIT-e7d8ad)](LICENSE)

Run tests, verify artifacts, and prepare an iOS release for review.

A small local CLI for independent developers. Connect your existing Xcode project,
test suite, screenshot lane and archive command through one TOML file. Every stage
must produce the artifacts it promises. Interrupted runs can resume after their
source, configuration, selected environment and completed artifacts are checked.

**Alpha · Python 3.11+ · zero Python runtime dependencies · macOS for Xcode stages**

[中文](README.zh-CN.md) · [Integration](INTEGRATION.md) · [Development workflow](DEVELOPMENT.md) · [Security](SECURITY.md)

## Try it in two minutes

```sh
git clone https://github.com/zemixo/ios-app-pipeline.git
cd ios-app-pipeline
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .

ios-pipeline plan --config pipeline.demo.toml
ios-pipeline run --config pipeline.demo.toml
```

The demo creates **synthetic JSON and a 16 × 16 PNG** to exercise orchestration.
It does not test an iOS app. A successful run prints:

```text
PASSED prepare-fixture
PASSED check-synthetic-image
READY_FOR_REVIEW <run-id>
```

To verify and reuse that run:

```sh
ios-pipeline run --config pipeline.demo.toml --resume <run-id>
```

The project is distributed from source; a PyPI release is not currently claimed.

## Bring your private app

Copy `pipeline.example.toml` into your app as `pipeline.local.toml`, customize its
steps and expected archive identity, and add these entries to that app's `.gitignore`:

```gitignore
.ios-pipeline/
pipeline.local.toml
```

```sh
export XCODE_PROJECT=MyApp.xcodeproj
export APP_SCHEME=MyApp
export TEST_DESTINATION='platform=iOS Simulator,id=YOUR_SIMULATOR_UDID'

ios-pipeline plan --project ~/Projects/MyApp --config ~/Projects/MyApp/pipeline.local.toml
ios-pipeline run --project ~/Projects/MyApp --config ~/Projects/MyApp/pipeline.local.toml
```

Use the Git working-tree root as `--project`. A dirty checkout is supported: the
fingerprint includes the current contents of tracked and non-ignored untracked
files. Changes during execution block the run. Keep generated build files in each
stage's output directory. Configure your screenshot lane and install the optional
preflight tool as described in [Integration](INTEGRATION.md).

Your app source stays in its own repository. The tool creates no remote repository,
pushes no source and contains no App Store Connect credentials or client.
**Configured commands are trusted code and may have their own side effects.**
Review them before using `run`; `plan` only validates and lists stages.

## What the checks establish

| Check | Evidence required |
|---|---|
| Files | Every declared path exists and contains regular-file data; hashes are recorded. |
| Xcode tests | A readable `.xcresult`, `Passed`, a reviewed minimum test count, and no failed, skipped or expected-failure tests. |
| Screenshots | Every declared image exists with valid PNG chunks, checksums and optional expected dimensions. |
| Archive | Inner app and archive metadata match the configured bundle ID, version and build. |
| Resume | Matching source/configuration/selected environment and unchanged completed outputs. |

The test gate enforces a count threshold; it does not discover missing business
scenarios or establish StoreKit, CloudKit or device-matrix coverage. PNG checks
do not establish visual quality. Archive checks do not establish distribution
signing, upload acceptance or App Review approval. Review those separately.

## An inspectable handoff

```text
private app → tests → preflight → screenshots → archive → READY_FOR_REVIEW
```

Each command has a fresh output directory, a timeout and a private log. A nonzero
exit, missing output or failed validator stops downstream stages. Failed attempts
are retained. The runner serializes runs within a project. It never automatically
retries a command that might have side effects.

Receipts live under `.ios-pipeline/runs/<run-id>/report.json`. They contain hashes,
stage status and validator evidence; command arguments and environment values are
not serialized. Logs and artifacts may still contain private data and remain local.
See [Security](SECURITY.md) before sharing any results.

## Scope of v0.1

Included: configurable execution, artifact validation, fail-fast behavior, resume,
private receipts, development/review templates, an optional preflight integration,
and a native acceptance fixture that generates its own small iOS app.

Publishing remains a deliberate handoff. App Store Connect upload, metadata
replacement, submission, billing changes and automatic AI code generation are
not built-in operations in this version. [Integration](INTEGRATION.md) explains
how to hand a reviewed archive to your established release process.

Fingerprinting currently rejects source symlinks and submodules. Git-ignored
inputs and installed tool versions are outside that fingerprint; declare relevant
environment variables, pin tools, and start a fresh run after changing them.

## Verify the tool

See the bounded [validation record](VALIDATION.md) for toolchain and test evidence.

```sh
python3 -m unittest -v test_ios_pipeline
# macOS with full Xcode, XcodeGen and an available iPhone Simulator:
python3 native_fixture.py
```

The native fixture creates its own simulator and synthetic app, exercises XCTest
and UI capture, validates an unsigned archive, and checks resume. It shuts down
its simulator afterward and leaves its data intact. To retain the synthetic
project and receipts, pass `--work-dir` with a new directory.

Created by **Zemixo**. Contributions: [CONTRIBUTING.md](CONTRIBUTING.md).
