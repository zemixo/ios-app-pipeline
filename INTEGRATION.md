# Connect an existing app

## 1. Make inputs explicit

Use a private `pipeline.local.toml` in the app's Git working-tree root. Begin with
`pipeline.example.toml`. Check in portable project configuration as appropriate;
keep account-specific settings and credentials outside this public toolkit.

The schema is version 1. Steps execute in declaration order. Each step has a unique
lowercase `id`, a `command` argument array, nonempty `outputs`, an optional `check`
(`files`, `xcresult`, `screenshots`, `archive`), and a positive `timeout` in seconds.
Unknown fields fail validation, so a misspelled check cannot silently disappear.

Arguments run without an implicit shell. `${NAME}` expands only a declared
environment name or one of these injected paths:

- `PIPELINE_PROJECT_DIR`: the selected private Git working tree.
- `PIPELINE_STEP_DIR`: a fresh directory for this stage attempt.
- `PIPELINE_PYTHON`: the interpreter running this CLI.
- `PIPELINE_STAGE_<ID>_DIR`: a completed earlier stage's directory, with ID
  uppercased and hyphens replaced by underscores. Example: `PIPELINE_STAGE_TEST_DIR`.

Outputs are exact relative paths beneath `PIPELINE_STEP_DIR`. List every required
language, device and screen explicitly. Shell interpolation, globs and `..` paths
are not output declarations. `command.log` can itself be declared as an output
for an analysis command whose report is written to stdout.

Declare every environment variable that can change the result, such as selected
SDK, feature switches or fixture modes. Declared variables must be nonempty.
Their combined hash is recorded alongside `PATH` and `DEVELOPER_DIR`; values are
kept out of the report. Tools inherit the process environment, so use a dedicated
build environment with only the permissions it needs.

## 2. Run actual tests

Use `xcodebuild test` with an explicit scheme, destination, derived-data directory
and result-bundle path. The Xcode validator reads that result bundle using
`xcrun xcresulttool get test-results summary`. Full Xcode with this command is
required. Set `DEVELOPER_DIR` for the current process when using a non-default
installation; there is no need to change the machine's global Xcode selection.

Set `minimum_tests` to a reviewed baseline. Maintain separate runs for required
destinations and configurations. Keep upgrade data, attachment integrity, purchase
restoration and synchronization scenarios in the app's private test suite.

Apple references: [command-line tools](https://developer.apple.com/documentation/xcode/xcode-command-line-tool-reference)
and [test results](https://developer.apple.com/documentation/xcode/running-tests-and-interpreting-results).

## 3. Add a preflight gate

Install [apple-presubmit-audit](https://github.com/zemixo/apple-presubmit-audit)
from a reviewed revision in the same environment. The example uses `--no-asc`
for source inspection and `--json` for structured output. Fields that require
App Store Connect remain unevaluated in that mode. A static preflight supplements
runtime tests and review; it cannot guarantee App Review acceptance.

## 4. Capture app-specific screenshots

Keep UI navigation and synthetic demo data in your private app's UI test target.
Use [fastlane snapshot](https://docs.fastlane.tools/getting-started/ios/screenshots/)
to capture selected devices and languages. For example, provide this lane in the
app's Fastfile and customize its scheme, devices and expected filenames:

```ruby
platform :ios do
  lane :pipeline_screenshots do
    capture_screenshots(
      scheme: "MyAppScreenshots",
      output_directory: File.join(ENV.fetch("PIPELINE_STEP_DIR"), "screenshots"),
      clear_previous_screenshots: false
    )
  end
end
```

Fastlane includes device names in its filenames. Update the example manifest's
output list to those exact names after reviewing a capture; the illustrative
`en-US/01-home.png` entries are not universal fastlane defaults. Use synthetic
content, wait for actual UI readiness, and visually inspect the exported screens.

## 5. Bind the archive to the reviewed version

The archive validator checks the archive's `ApplicationProperties` and the built
app's `Info.plist` against `bundle_id`, `version` and `build`. Preserve identity
and existing entitlements when configuring the app. Signing verification,
distribution export and server-side validation are additional release checks.

## 6. Review, then publish through your release process

The final report has state `ready_for_review`. Review the test matrix, screenshots,
preflight findings, release notes, privacy declarations and exact archive identity.
Use your existing signing/export and upload process for that archive; then read
back the server's build identity and processing status before selecting a build
for review. [fastlane build_app](https://docs.fastlane.tools/actions/build_app/)
and [TestFlight upload](https://docs.fastlane.tools/actions/upload_to_testflight/)
are useful integration points.

This version has no built-in upload, screenshot replacement or submission command.
Do not treat a local exit code as evidence of an App Store state change. If you
configure a custom command that changes an external service, review and authorize
that action independently and verify the resulting service state.

## Resume boundaries

A failed attempt remains on disk. `--resume` checks completed artifact hashes and
reuses them, then retries the first incomplete stage in a fresh directory. Retrying
an interrupted external command may duplicate its effects: check the service
first. Start a new run after changing source/configuration/declared environment,
ignored inputs, dependencies, Xcode or other tool versions. Receipts are local
integrity records, not signed attestations or a sandbox against malicious commands.
