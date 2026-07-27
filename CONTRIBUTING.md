# Contributing to FGOps

Thank you for helping improve FGOps. This project controls a security-sensitive device-change path, so contributions must remain reviewable, testable, and evidence-based.

## Before opening an issue

- Search existing issues and pull requests.
- Remove credentials, private keys, production IP addresses, hostnames, FortiGate backups, package files, bot tokens, and unsanitized logs.
- State the affected FGOps version, Python version, FortiGate model, FortiOS branch/build, execution policy, and package family when relevant.
- Separate confirmed observations from hypotheses.

Security vulnerabilities and suspected credential exposure must follow [`SECURITY.md`](SECURITY.md), not a public issue.

## Development setup

```powershell
py -3.13 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Run the local checks before opening a pull request:

```powershell
& .\.venv\Scripts\python.exe -m compileall -q src tests
& .\.venv\Scripts\python.exe -m pytest --cov=fgops --cov-report=term-missing
& .\.venv\Scripts\python.exe -m ruff check src tests
```

## Pull request requirements

1. Create a focused branch from the current `main` branch.
2. Keep each pull request limited to one coherent change.
3. Add or update tests for behavioral changes.
4. Update documentation when commands, configuration, state, evidence, safety gates, or supported behavior change.
5. Do not weaken host-key pinning, target identity validation, mandatory backup, package allowlists, downgrade protection, prompt rejection, version verification, or fail-closed behavior without an explicit security review.
6. Do not add production data or third-party package files to the repository.
7. Ensure CI passes on Python 3.11, 3.12, and 3.13.

## Documentation standard

Operational claims must be supported by code, tests, or produced validation evidence. Do not describe an unvalidated model, FortiOS branch, package publisher, or database family as supported. Mark assumptions, planned behavior, and target-specific findings explicitly.

Use documentation-only example addresses from the IANA TEST-NET ranges, such as `192.0.2.0/24`, rather than real management addresses.

## Commit messages

Use concise imperative messages, for example:

```text
fix: reject ambiguous restore completion
feat: add bounded package-version polling
test: cover changed host-key rejection
docs: clarify approval-mode first-run gate
```

## Review and merge

Changes are merged through pull requests after review and successful CI. The maintainer may request additional tests, sanitized evidence, rollback notes, or narrower scope before merge.
