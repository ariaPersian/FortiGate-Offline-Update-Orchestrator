# Private repository synchronization

The authoritative FGOps source repository is:

```text
https://github.com/ariaPersian/FortiGate-Offline-Update-Orchestrator-Private
```

Production checkouts must not pull from the former public repository. The runtime path does not require GitHub, but upgrades must be sourced from the private repository and reviewed before installation.

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
  -m pip install --upgrade --no-user C:\FGOps

& C:\FGOps\venv\Scripts\python.exe -m pip show fgops
```

Run a foreground check after the upgrade:

```powershell
& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  status
```

Inspect the daily runtime log and re-enable scheduling only after the installed version and foreground outcome are accepted:

```powershell
$Today = Get-Date -Format "yyyy-MM-dd"
Get-Content "C:\ProgramData\FGOps\logs\fgops-$Today.log"

Enable-ScheduledTask -TaskName "FGOps Offline Update Monitor"
```

## Recovery of preserved local work

List the safety artifacts:

```powershell
git branch --list "backup-before-private-sync-*"
git stash list
```

Recover only reviewed files. Do not restore runtime data, credentials, backups, package files, production configuration, or logs into the repository. Prefer copying an individual source or documentation file from the safety branch rather than merging the entire historical branch.
