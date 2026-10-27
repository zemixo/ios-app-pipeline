# Privacy and security

The public repository contains generic tooling and synthetic fixtures. The runner
works inside a user-selected private Git working tree and stores results locally.
It does not read an Apple keychain, discover App Store credentials, create remote
repositories, push source, or call App Store Connect itself.

## Trusted configuration

Treat a pipeline manifest like a shell script: it can execute arbitrary programs
with your user's permissions. Review commands and invoked scripts before `run`.
Argument arrays remove implicit shell interpolation; they do not sandbox a shell
or interpreter explicitly named by a command. Tools inherit your environment.

## Local records

`.ios-pipeline` directories use owner-only permissions; reports and captured logs
use mode 0600. Reports omit raw arguments and environment values. Child output is
kept in private logs instead of echoed to the terminal. Child tools can still log
secrets, write elsewhere or use the network. Review any file before sharing it.

Keep credentials outside the public repository and configure tools through your
existing secret manager or CI secret store. Add `.ios-pipeline/` and local config
files to each app's ignore rules. Ignore rules do not remove previously tracked
files or Git history; audit staged contents and history before publishing.

## Integrity limits

Hashes detect accidental changes to source and recorded outputs. Someone able to
edit both an artifact and its receipt can replace both; receipts are not signed
attestations. Ignored files, network inputs and external tool versions are outside
the source fingerprint. Pin dependencies, declare relevant environment variables,
and use a new run when those inputs change. Source symlinks and submodules are
currently rejected instead of being silently fingerprinted incompletely.

## Reporting

For a sensitive report, contact [Zemixo](mailto:zemixo.git@gmail.com). Include a
minimal synthetic reproduction. Do not attach real credentials, receipts,
customer data, private app source or unreviewed execution logs to public issues.
