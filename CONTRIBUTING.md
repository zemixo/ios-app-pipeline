# Contributing

Start with a reproducible problem and a focused change. Use synthetic fixtures.
For a new validator, cover both a valid artifact and the failure it is intended
to catch. Preserve the distinction between orchestration checks and native iOS
acceptance. Keep public examples independent of personal directories and accounts.

```sh
python3 -m unittest -v test_ios_pipeline
python3 -m py_compile ios_pipeline.py demo_fixture.py native_fixture.py
git diff --check
```

The native CI job generates its own iOS fixture. Changes affecting Xcode, archive
or screenshot integration should pass that job. No live Apple account or paid
developer credentials are needed for the synthetic test and unsigned archive.

Use AI assistance responsibly: review and understand the result, verify behavior,
and disclose substantial assistance in the PR. Do not submit unreviewed output,
invented test results or changes that contain private source/data.

Keep additions within the local release-preparation scope. Discuss changes to
the manifest schema or external service writes before implementing them.
