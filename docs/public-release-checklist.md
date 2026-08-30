# Public release checklist

Use this checklist before changing repository visibility or publishing a sanitized development snapshot.

## 1. Treat history as publishable data

Changing visibility exposes the current tree, commit history, merged pull requests, issues, Actions history, logs, and retained artifacts. Deleting a sensitive value only from the latest branch does not remove it from earlier commits.

Review all branches, tags, merged pull requests, workflow logs, and downloadable artifacts for:

- credentials, tokens, passwords, private keys, and encrypted-secret exports;
- production IP addresses, hostnames, usernames, SSH fingerprints, and internal URLs;
- FortiGate configuration backups and unsanitized command output;
- update archives, package files, evidence bundles, and operational logs;
- operator health reports from `C:\ProgramData\FGOps\reports\health`;
- customer, organization, site, or asset identifiers;
- third-party content that the project is not authorized to redistribute.

Rotate or revoke any credential that has ever entered Git history, even when the credential was later removed.

## 2. Prefer a clean public history when sanitization is uncertain

For a repository developed with production validation data, the lowest-risk publication model is a new public repository created from the sanitized current tree with fresh history. Preserve the original private repository as the restricted engineering and evidence archive.

If preserving existing history is required, rewrite sensitive history with an appropriate Git history-filtering tool, force-push every affected branch and tag, remove obsolete pull-request references where possible, and re-scan before publication. Coordinate this operation with every collaborator because existing clones retain the old objects.

## 3. Verify the public tree

Confirm that:

- `README.md`, `LICENSE`, `SECURITY.md`, and `CONTRIBUTING.md` are present;
- documentation uses TEST-NET example addresses rather than production addresses;
- example configuration contains placeholders only;
- `.gitignore` excludes runtime data, backups, keys, local configuration, logs, and generated health reports;
- no `fgops-health-*.txt` or `fgops-health-*.json` file is tracked;
- no package archive or FortiGate configuration file is tracked;
- the package metadata and license file agree;
- CI passes on the supported Python versions;
- operational claims are limited to validated evidence.

The source file `scripts/health_report.py` is safe to publish only when its defaults and examples remain sanitized. The script must never embed production device addresses, credentials, secret values, customer identifiers, or copied runtime evidence.

The default expected private-repository URL is operational metadata rather than a secret, but publication must not imply that the public repository is the authoritative production source.

## 4. Review generated operator artifacts

The health script writes timestamped TXT and JSON reports below the runtime root:

```text
C:\ProgramData\FGOps\reports\health
```

These files can contain:

- production Git origin and branch information;
- device identity and FortiOS version/build;
- package and FortiGuard object versions;
- manifest IDs;
- backup and report paths;
- Task Scheduler state and timing;
- health failures and suggested actions.

They do not intentionally contain plaintext secret values, but they are still sensitive operational records. Never copy unsanitized health reports into the repository, a public issue, pull request, Actions artifact, or release asset.

## 5. Configure repository security

After publication:

- enable secret scanning and push protection;
- enable dependency graph, Dependabot alerts, and Dependabot security updates;
- enable code scanning when an appropriate workflow is available;
- protect `main` and require pull requests plus successful CI where supported;
- restrict GitHub Actions permissions to the minimum required;
- review public issue templates and vulnerability-reporting instructions;
- inspect the public Community Standards checklist.

## 6. Final visibility gate

Do not change visibility until the maintainer records all of the following:

```text
CURRENT_TREE_SANITIZED=yes
FULL_HISTORY_REVIEWED_OR_CLEAN_PUBLIC_REPOSITORY_CREATED=yes
ACTIONS_LOGS_AND_ARTIFACTS_REVIEWED=yes
HEALTH_REPORTS_AND_RUNTIME_EVIDENCE_EXCLUDED=yes
CREDENTIALS_ROTATED_IF_EXPOSED=yes
LICENSE_CONFIRMED=yes
CI_GREEN=yes
PUBLIC_SECURITY_SETTINGS_PLANNED=yes
```

After the visibility change, verify the repository from a signed-out browser session and immediately review the Security tab for alerts.
