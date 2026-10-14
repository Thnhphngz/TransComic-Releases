# B2.2 preparation: signing and version policy

## 1. Current version and scope

Source VERSION remains **0.1.0**. This is preparation only. Production execution guards, empty production trust maps, frozen build guard and ISS guard remain active. No production key, pin, EXE, installer, Git commit/tag/push, GitHub write or translation API request was made.

## 2. Numbering policy

`transcomic/release_version.py` implements the TransComic policy: stable, canonical MAJOR.MINOR.PATCH; MINOR and PATCH range 0–9. Patch carries into minor, minor carries into major. Explicit invalid input is rejected without normalization. Generic `update.metadata.SemVer` and generic `bumped()` are unchanged; external updater metadata can use `1.0.100` or `1.10.0`.

## 3. Required examples

| Current | Patch proposal |
|---|---|
| 0.1.0 | 0.1.1 |
| 0.1.8 | 0.1.9 |
| 0.1.9 | 0.2.0 |
| 0.9.9 | 1.0.0 |
| 1.0.1 | 1.0.2 |
| 1.0.8 | 1.0.9 |
| 1.0.9 | 1.1.0 |
| 1.1.9 | 1.2.0 |
| 1.9.9 | 2.0.0 |
| 2.9.9 | 3.0.0 |
| 9.9.9 | 10.0.0 |

Manual minor: 1.2.4→1.3.0, 1.9.4→2.0.0. Major: 1.2.4→2.0.0. Release policy rejects 1.0.10, 1.0.100, 1.10.0 and pre/build suffixes. Ordering uses numeric SemVer.

## 4. Consumers

ReleaseWorkflow, ReleaseJournal and preflight use the new policy. `version_outputs()` validates release versions and supplies tag/title/installer/ISS/EXE tuple. Existing BuildAdapter writes only a staged VERSION overlay; PyInstaller/ISS/manifest consume the reserved version. Actual source VERSION is not modified during preparation. Updater parser, selection, service and UI remain unchanged.

## 5. Retry and remote uncertainty

Reservation is persisted before effects. Failed/unknown 1.0.9 resumes 1.0.9; verified published evidence permits the next new intent to propose 1.1.0. Same intent returns the confirmed reservation. Independent evidence requires exact tag, build ID, verified assets and mutually exclusive published/draft flags.

BAT remains preflight. Its read-only journal default is `.release-state/journal.json`; it never reserves or locks this journal. Production activation must wire the coordinator to this same journal. Preflight checks Latest and the complete release list, preserving any existing reservation. A remote draft/tag/published release cannot be reconciled from CLI success alone: `RELEASE_STATE_UNCERTAIN` stops the plan. Timeout, missing evidence, changed source/version, manually edited assets and conflicting remote identity never trigger deletion, replacement or blind publication. A 404 means no Latest only with an independently verified empty release list.

## 6. Provisioning audit

Ed25519 is provided by cryptography; generation uses its cryptographic RNG. Private storage uses password-encrypted PKCS8 (`BestAvailableEncryption`), chosen instead of DPAPI-only storage. Provisioning uses exclusive creation, encrypted writes/fsync, private/public pair verification and a public-key-derived ID. Test IDs have a distinct `test-` namespace. Production methods and Windows ACL operations still fail before side effects. Signing now checks key type, public pair, derived ID, purpose and active production pin; errors omit secret contents.

Windows ACL source restricts the directory/key to the current owner with protected DACL and verifies both owner SID against the current token and ACE rights. **Native ACL execution has not been validated in this preparation**; FakeACL tests prove application rejection logic, not OS enforcement. No native permission claim is made.

## 7. Production storage

Prepared policy requires `%LOCALAPPDATA%\TransComicSigning\production`, outside workspace and any Git tree, with no reparse ancestors and no known OneDrive root. LOCALAPPDATA redirection/cloud/security policy must be reviewed before activation. No default plaintext fallback, automatic regeneration or overwrite is allowed. Passphrases belong in an approved password manager, separate from the offline backup.

## 8. Private and public keys

Private key and recovery backup must never enter conversation output, Git, EXE, installer, release artifacts or uploads. Gitignore also excludes `.testkey` and `.tc-keybackup`; packaging uses explicit program resources and publisher accepts only the required installer/manifest/checksum inventory. Gitignore is not a substitute for storage policy. Public key/ID/purpose may be reported. Production public pin/status maps remain empty. A real public pin needs separate approval after real provisioning, pair check and restore drill; no fixture pin is accepted.

## 9. Portable recovery

Implemented backup format 1: Scrypt N=131072,r=8,p=1 (random 16-byte salt), AES-256-GCM (random 12-byte nonce), authenticated canonical header binding format/purpose/key ID/public key/KDF/cipher. Payload is itself encrypted PKCS8 under a distinct recovery passphrase. There is no plaintext disk/temp output. Backup is exclusive, permission checked and fsynced. Restore validates bounded schema, authentication, purpose and public pair before creating a destination; writes newly encrypted PKCS8 under the new machine password, preserving key ID. Existing destinations are rejected; partial output is retained for review after write/ACL failure.

Test keys were restored in a second directory with a new password and used to sign/verify. Wrong passwords, modified header/ciphertext, production-purpose substitution, malformed/missing file and ACL rejection fail closed without creating a restored directory. This is portable encryption, not a DPAPI identity transfer. A real backup needs an offline device, separately stored recovery passphrase, native ACL verification and an actual recovery drill before `PRODUCTION_KEY_RECOVERY_NOT_READY` can be cleared.

## 10. Before real provisioning

Separate user approval, reviewed provisioning-only source activation, audited native ACL/storage handling, destination review, strong password custody and an offline backup destination are required. Keep release/build/install/publisher guards locked during provisioning. Commit reviewed source and verify exact clean provenance. Existing incomplete key directories require manual investigation, never an automatic new key.

## 11. Prepared commands

Safe test demonstration now:

```powershell
python scripts/provision_release_key.py --test
```

It generates, backs up and restores an ephemeral test key, prints public information only and deletes its temporary directory.

After separate approval **and reviewed provisioning-only activation** (these production commands currently stop before password prompts/file access):

```powershell
python scripts/provision_release_key.py --operation provision --directory "$env:LOCALAPPDATA\TransComicSigning\production"
python scripts/provision_release_key.py --operation backup --directory "$env:LOCALAPPDATA\TransComicSigning\production" --backup-file "E:\TransComicOffline\release-key.tc-keybackup"
python scripts/provision_release_key.py --operation restore --directory "$env:LOCALAPPDATA\TransComicSigning\recovery-drill" --backup-file "E:\TransComicOffline\release-key.tc-keybackup"
```

`E:\TransComicOffline` is an example offline device directory: approve the actual drive and create/restrict its parent first. Passwords are prompted with getpass, never passed through argv/environment. Restore prompts for a new storage password and the offline recovery password. No manual key material is entered. Compare restored public ID/key, sign/verify a canonical fixture, then approve only the public pin. Real publication must remain blocked until this drill succeeds. Loss of both encrypted backup and original key, or the recovery password, is not recoverable by this tool.

On a new Windows identity, old NTFS ownership is not portable. Import **only the encrypted backup** into a directory owned by the new user and apply/verify the protected owner-only DACL through the separately approved native provisioning procedure before restore. An unreadable or unverified backup ACL remains a blocker; the restore command never bypasses it. The test-key drill validates portable cryptography, not native cross-machine permission transfer.

## 12. Source provenance

Read-only inspection confirmed HEAD `6fd3f061c3c78fcae3ec4ebd467858346441ff56`, branch main, initially clean, 174 tracked files, zero untracked files and no origin remote. Privacy is unknown; a local repository does not imply public/private remote verification. Changes from this task are intentionally uncommitted. Source commit must be the reviewed final committed code, not the old baseline; source identity must never be replaced by distribution SHA.

## 13. Distribution repository

Read-only GitHub inspection confirmed public `Thnhphngz/TransComic-Releases`, main commit `6dc2d5378d27eb90a455b473b306fdd5d988da66`. Latest currently returns 404. No distribution initialization or GitHub writes were performed. This commit describes distribution history, not application source provenance.

## 14. Authenticode and environment

Git 2.55.0.windows.5, gh 2.102.0, PyInstaller 6.22.0 were observed. Inno was found dynamically outside PATH; PE fixed version returns 0.0.0.0, so compiler version remains unverified rather than assuming the user-reported 6.7.3. SignTool was not detected. Public Stable still requires valid Authenticode certificate/publisher/timestamp on app/helper/installer: `AUTHENTICODE_CERTIFICATE_NOT_READY`. Ed25519 authenticates update metadata; it does not replace Windows publisher trust.

SignTool is supplied through the [official Windows SDK](https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool). Obtain the SDK from Microsoft's linked download and select signing tools; installation requires separate authorization and was not performed. Certificate selection/identity and native chain verification remain required.

## 15. Unit/integration evidence

Final focused release/updater suites: **263 passed, 11.34s**, before the encoding correction described below. New tests cover all carry examples, explicit/manual validation, generic external SemVer candidate, synchronized outputs, failed/unknown reservation recovery, mock publish response loss, read-only preflight, encrypted portable recovery, tamper/ACL/password/purpose/missing-file rejection, locked production calls and storage policy. Existing signature/rotation/revocation/hash/download/install/Safe Exit/certificate tests remain in regression.

Exploratory new tests initially failed due to an incorrect expectation of an exception rather than the existing NOT_READY return, then a fixture unpacking mistake. Both assertions now check the actual fail-closed contract. An initial GUI run exposed accidental text encoding damage in the edited smoke script; original UTF-8 text was restored and its assertions were retained. Logs are kept, not discarded.

## 16. Full regression

Preliminary full suite: **712 passed, 1 skipped, 181.33s**. A second preliminary suite was already running when the final preflight inconsistency gate/test was added; it is not evidence for identical final code. Final consecutive full suites will be recorded below. No assertion/deadline weakened, existing skips retained, API ledgers untouched. Prior B2.1 Safe Exit 900ms timing failures remain documented in that report; this task does not claim to fix them. Final focused policy suite after the additional gate: **39 passed, 4.94s**.

## 17. Windows GUI

Native Windows entry point, isolated temporary LOCALAPPDATA and HTTP guards. Light/Dark; actual measured DPR 1/1.25/1.5; update available, download/progress/cancel, hash rejection, offline response, mock helper and logger-flush block. No auto-install or installer process. New evidence lives under `artifacts/release-signing-and-version-policy/windows`; final results appended below.

All three measured DPR reports passed. The final subsequent code change adds only a preflight uncertainty gate and its test; GUI/runtime/update source is identical to these GUI runs.

## 18. Remaining production blockers

Production key/pin/real recovery drill absent; native ACL proof absent; SignTool and certificate absent; Inno version verification; committed final source provenance; isolated hash-locked wheel environment; reviewed source activation; native helper readiness acknowledgement/process locking/restart health and installer/update VM tests. Backend/UI/SQLite/DPAPI/Safe Exit source remains outside the edit scope. Test-only encryption evidence cannot clear production security blockers.

## 19. Separate confirmations

First approve storage/passphrase custody/offline recovery destination and provisioning-only activation, then one-time key creation + backup/restore drill. Public pin requires subsequent approval of the generated public material. Certificate/tool installation and native signing/VM install-update tests require their own authorization. Build/tag/draft/upload/publish rights are not implied by provisioning approval.

## 20. Before real B2.2 build

All blockers above must be resolved, final code committed/clean with exact source SHA, production key/pin/backup verified, Authenticode configured, and build/install/release actions separately authorized. Keep journal identity and previous published evidence across retries, stage version overlays only, verify all uploaded signed assets independently, and record success only after confirmed publication. Current BAT remains dry-run.

## Final acceptance

**SIGNING + VERSION POLICY READY FOR APPROVAL** ? preparation code and test evidence only; production release remains blocked.

| Final full suite | Passed | Skipped | Time |
|---|---:|---:|---:|
| 1 | 713 | 1 | 182.70s |
| 2 | 713 | 1 | 183.10s |

Both complete runs used identical final runtime/scripts/tests/spec/ISS/BAT/dependency-lock bytes, recorded in `artifacts/release-signing-and-version-policy/source-final.json` and checked after both runs. Existing tests/skips/Safe Exit deadlines/API ledgers were retained. Preliminary runs: 712 passed/1 skipped in 181.33s and 201.94s; the latter crossed the final preflight code edit and is excluded from the final pair.

GUI measured DPR 1.0/1.25/1.5 passed Light/Dark and all documented mock scenarios; source for UI/updater/backend is unchanged relative to baseline. `scope.json` records an empty protected-source Git diff and unchanged HEAD/main. Production key destination is absent; no private key content was inspected. Working tree is intentionally dirty and no source commit/tag/push was made.

Evidence: `artifacts/release-signing-and-version-policy/acceptance.json`, `regression-final-1.log/xml`, `regression-final-2.log/xml`, `focused-last.log`, `environment.json`, `preflight.json`, `scope.json`, `gui-summary.json` and `windows/*/report.json`/screenshots. Earlier failed exploratory checks are retained separately.

Next approval concerns provisioning-only activation and one-time production key creation/storage/backup/restore drill (request section 5 explicitly requires separate confirmation). Production pin approval follows real public pair verification. Build/install/GitHub write permissions remain separate.
