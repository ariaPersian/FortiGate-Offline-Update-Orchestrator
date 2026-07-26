# Standalone VM agent

FGOps v0.2 makes a local scheduled agent the primary deployment model for a single FortiGate.
GitHub remains the source repository; it is not required in the runtime path.

## Runtime flow

```text
configured source page
  -> discover the Fortigate V6.4 download link
  -> bounded atomic ZIP download
  -> SHA-256 duplicate detection
  -> safe ZIP extraction
  -> package classification and immutable manifest
  -> local execution plan
  -> future SSH/TFTP apply gate
```

The source parser matches against the surrounding list-item text as well as the anchor text and URL.
This is required because the Cyberlogic page presents `Fortigate V6.4` outside the anchor while the
anchor itself is labelled `دانلود`.

## Local state

The agent stores state in JSON outside the repository. An archive is identified by SHA-256, not by
page timestamp, URL, filename, or HTTP metadata. A source may therefore reuse one URL while changing
the ZIP contents without being missed.

The state file records:

- processed archive hashes;
- source URL and local archive path;
- manifest ID and quarantine directory;
- planned package kinds;
- last run result and error.

State writes are atomic. Unknown package types fail closed by default.

## Current safety boundary

Version 0.2 performs source monitoring, download, extraction, inventory, deduplication, and local plan
generation. It does not yet log in to a FortiGate, start TFTP, answer restore prompts, or change a
device. Configuration values `approval` and `unattended` are accepted for forward compatibility, but
the orchestrator records that device execution remains blocked.

The next gate adds read-only SSH preflight and target identity validation before any TFTP or restore
operation is introduced.

## Windows deployment

```powershell
py -3.12 -m venv C:\FGOps\venv
C:\FGOps\venv\Scripts\python.exe -m pip install .

C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  init --package-map-source .\config\fortios64-package-map.yml

C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  validate-config

C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  run --dry-run
```

After the dry run succeeds, install the scheduled monitor from an elevated PowerShell session:

```powershell
.\scripts\install-scheduled-task.ps1 `
  -AgentExecutable C:\FGOps\venv\Scripts\fgops-agent.exe `
  -ConfigPath C:\ProgramData\FGOps\config.yml `
  -IntervalHours 6
```

The task runs as Local System, prevents overlapping runs, retries transient failures, and starts missed
runs when the VM becomes available. Production credentials are not part of this milestone and must not
be added to the YAML file.
