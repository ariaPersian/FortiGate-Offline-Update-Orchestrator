# Private repository synchronization

The authoritative FGOps source repository is:

```text
https://github.com/ariaPersian/FortiGate-Offline-Update-Orchestrator-Private
```

Production checkouts must not pull from the former public repository. The runtime path does not require GitHub, but upgrades must be sourced from the private repository and reviewed before installation.

The operator-health update adds `scripts/health_report.py`. Production should rely on that script only after the reviewed change has also been synchronized into the authoritative private `main` branch.

## Verify the current remote

From an elevated PowerShell session:

```powershell
Set-Location C:\FGOps

git remote -v
git status
git branch --show-current
```

The expected fetch and push URL is:

```text
https://github.com/ariaPersian/FortiGate-Offline-Update-Orchestrator-Private.git
```

The default health report also checks this exact production origin and reports `HC-02=FAIL` when the checkout points elsewhere.

## Switch an existing public checkout safely

A checkout that previously tracked the public repository can have a different or rewritten `main` history. Do not merge or rebase those histories into the production checkout merely to resolve a fast-forward error.

Preserve local work first:

```powershell
Set-Location C:\FGOps

$SafetyBranch = "backup-before-private-sync-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
git branch $SafetyBranch

git stash push `
  --include-untracked `
  -m "Safety stash before switching FGOps origin to private repository"
```

Change the remote and fetch the private history:

```powershell
git remote set-url origin `
  "https://github.com/ariaPersian/FortiGate-Offline-Update-Orchestrator-Private.git"

git fetch --prune origin
git remote -v
```

Align the production checkout with the authoritative private `main` branch:

```powershell
git switch main
git reset --hard origin/main
```

The reset is destructive to the current working tree, which is why the safety branch and stash are mandatory when local work may exist.

## Interpret a forced-update or divergence message

A fetch can report:

```text
(forced update)
fatal: Not possible to fast-forward, aborting.
```

This means the local branch is not a direct ancestor of the fetched branch. For the production FGOps checkout, the safe response is:

1. keep the old state in a safety branch;
2. stash uncommitted and untracked files;
3. confirm `origin` points to the private repository;
4. fetch the private branch;
5. reset local `main` to `origin/main`;
6. inspect the safety branch or stash separately if any local work must be recovered.

Do not use `git merge --no-ff` or an automatic rebase to combine the former public history with the authoritative private production branch unless that integration is intentionally reviewed as a separate development task.

## Upgrade the installed agent

Disable the Scheduled Task before changing source files or the virtual environment:

```powershell
Disable-ScheduledTask -TaskName "FGOps Offline Update Monitor"

Set-Location C:\FGOps
git fetch --prune origin
git switch main
git reset --hard origin/main

& C:\FGOps\venv\Scripts\python.exe `
  -m pip install --upgrade --force-reinstall --no-deps C:\FGOps

& C:\FGOps\venv\Scripts\python.exe -m pip show fgops
```

Confirm that the reviewed private checkout contains the operator health script:

```powershell
Test-Path "C:\FGOps\scripts\health_report.py"
```

Expected:

```text
True
```

Run the normal maintenance validations while the Scheduled Task remains disabled:

```powershell
& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  validate-config

& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  status

& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  run --dry-run
```

A deliberately disabled Scheduled Task is considered unhealthy by the normal-state health report. Do not use `OverallHealth` as the pre-enable maintenance gate.

After the source, installed package, configuration, state, and dry-run outcome are accepted, restore scheduling:

```powershell
Enable-ScheduledTask -TaskName "FGOps Offline Update Monitor"
```

Then run the full normal-state operator health report:

```powershell
& "C:\FGOps\venv\Scripts\python.exe" `
  "C:\FGOps\scripts\health_report.py"
```

The report validates, among other checks:

- production Git origin and `main` branch;
- installed/source version parity;
- fail-closed execution policy;
- required secret metadata;
- Scheduled Task state, last result, next run, and `cycle` action;
- unresolved `APPLY_FAILED` / `REVIEW_REQUIRED` state;
- latest scheduled cycle result;
- latest encrypted backup and apply report;
- UDP/69 idle state and runtime disk capacity;
- pinned read-only FortiGate preflight;
- current FortiGuard versions against latest apply evidence.

Generated reports are stored under:

```text
C:\ProgramData\FGOps\reports\health
```

A `WARNING` result requires review. A `CRITICAL` result means at least one check failed; do not start a new apply until the failed checks are resolved or explicitly accepted under an authorized maintenance exception.

See [Operator health report](operator-health-report.md) for the complete interpretation table.

## Recovery of preserved local work

List the safety artifacts:

```powershell
git branch --list "backup-before-private-sync-*"
git stash list
```

Recover only reviewed files. Do not restore runtime data, credentials, backups, package files, production configuration, logs, or health reports into the repository.

Prefer copying an individual source or documentation file from the safety branch rather than merging the entire historical branch.

## Public/private synchronization requirement

The public repository can be used for sanitized development and documentation review, but production remains private-source authoritative.

When a reviewed feature is first developed publicly, such as `scripts/health_report.py`, synchronize the exact reviewed source and documentation into the private repository before instructing production operators to pull it. Do not make the production VM temporarily track the public origin simply to obtain one file.
