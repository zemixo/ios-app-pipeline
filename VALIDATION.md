# Validation record

## 2026-10-27 — initial alpha

- Python unit and failure-path suite: **22 tests passed**.
- Source installation, CLI plan and synthetic demo: **passed**.
- Wheel and source distribution: **built; twine metadata checks passed**.
- Native toolchain: **Xcode 27.0 (27A5252f), XcodeGen 2.44.1**.
- Native destination: **iPhone 17 Pro Simulator, iOS 26.1**.
- Synthetic native fixture: **2 tests passed, 0 failed, 0 skipped**.
- UI test captured the synthetic app screen; PNG validation: **1206 × 2622**.
- Unsigned iOS archive identity: **matched the configured bundle/version/build**.
- Resume: **all 3 completed stages verified and reused**.

The first native run exposed an integrity timing bug: reading an xcresult with
this Xcode version creates `database.sqlite3` inside the bundle. The runner now
records the full bundle after the reader completes. A regression test checks
that the added file remains covered by the artifact hash. A fresh native run
then passed, including screenshot extraction and resume.

These results cover the generated fixture and the orchestration tool. They do
not establish compatibility with every Xcode/runtime combination, acceptance of
a commercial app, physical-device behavior, distribution signing, StoreKit,
CloudKit, TestFlight upload or App Review. CI provides an independent native run
on its selected macOS/Xcode image.
