# From a product idea to a reviewable release

Use this template inside your private app repository. The public pipeline contains
workflow conventions; your product code, customer data and business plans stay
in that repository.

## Product brief

- Who uses this app, and what concrete task should they finish?
- Which three user flows define the first release?
- What data is stored, synchronized, exported or sent to external services?
- Which devices, languages and accessibility modes are supported?
- What is intentionally outside this release?

Write observable acceptance criteria for each flow. Connect every marketing or
paywall claim to an implemented capability and a corresponding verification step.

## Implementation task for a developer or coding assistant

```text
Goal:
User-visible behavior and acceptance criteria:
Canonical project and permitted files:
Existing data, identity and entitlement compatibility requirements:
Allowed external services and data transmission:
Tests and UI evidence required:
Commands allowed in this task:
Explicitly authorized release actions, if any:
```

Review the resulting code and run the project-native tests. Keep any required
automation disclosures. Assistant prose, generated tests and a successful build
do not establish that a device flow works.

## Review matrix

| Area | Evidence to retain privately |
|---|---|
| Core flows | Expected state, actual state, errors and recovery |
| Existing data | Upgrade over prior data; IDs, relationships and attachment hashes |
| Purchases | Verified transactions, entitlement delivery, restoration and revoked states |
| Sync | Separate source/destination devices, conflict and offline recovery |
| Interface | Device size, languages, appearance, accessibility and actual screenshots |
| Release | Source revision, test receipts, archive identity, signing and service readback |

Record `PASS`, `FAIL`, `BLOCKED`, `NOT_RUN` or `N/A` with an explanation. Retain
failures when later runs pass; make the change and revalidation traceable.

## First-release boundaries

The repository supplies the local execution and artifact gates. Product research,
code generation and domain-specific acceptance remain deliberate developer tasks.
Bring your preferred editor or coding assistant using the task template above.
Do not put production credentials or customer samples into prompts or fixtures.
