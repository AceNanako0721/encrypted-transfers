# Encrypted Transfers

A reusable public GitHub Releases inbox for temporary, password-encrypted transfers. **This repository contains tooling, not plaintext payloads.**

## Security model

- Each transfer gets a random opaque ID, an independent 256-bit random password, and a `.7z` asset.
- 7-Zip AES-256 encrypts content **and filenames** (`-mhe=on`). Use a maintained 7-Zip-compatible application; do not rely on Windows' built-in archive handler for encrypted 7z.
- Passwords are passed to 7-Zip through stdin, never in command-line arguments. They are stored locally with owner-only permissions and never uploaded.
- GitHub still sees upload timing, account, archive size, and download metadata. Encryption does not authorize sharing restricted corporate data.
- Public ciphertext can be saved indefinitely. Removing a Release is **not** guaranteed erasure from caches or third parties. Never publish a password beside its archive.
- This is an occasional file-transfer utility, not a backup service or CDN. Respect GitHub policies and current release-asset limits.

## Requirements

Python 3.10+, official `7zz`/`7z`, `git`, and authenticated `gh` with permission to manage this repository. Packing is local; GitHub Actions never receives plaintext or passwords.

## Workflow

```sh
python3 transfer.py pack /path/to/project
python3 transfer.py publish transfer-<timestamp>-<random>
python3 transfer.py list
# ONLY after the intended recipient confirms successful download/extraction:
python3 transfer.py delete transfer-<timestamp>-<random>
```

Review the source and Git history for secrets **before** packing. Packing includes a standalone `.git` directory (including configuration, hooks and object database) if present. Linked Git worktrees, shallow/partial/promisor clones, alternates, grafts, and symlinks are refused; convert to a reviewed standalone full clone first. Stop writers during snapshot creation if a point-in-time-consistent copy is required. The tool verifies the copied snapshot, not an atomic snapshot of a changing application.

Outside `.git`, defaults exclude runtime `local-data` contents (but preserve `.gitkeep` placeholders), virtual environments, dependency/cache directories, `.env` and `.env.*`, `settings.json`, `secrets.json`, Python bytecode, logs, and common database suffixes. These are convenience exclusions, **not a secret detector**. Other file names and Git history can still contain sensitive data. Full payload inspection is the operator's responsibility.

A private in-archive manifest records every included file's SHA-256 and excluded paths. Packing extracts the exact archive into a temporary directory, compares every file hash, checks Git object integrity, and verifies that an incorrect password cannot list the encrypted header. Temporary plaintext is removed on normal exit (not forensic secure erasure).

Publishing first creates a draft Release, uploads ciphertext plus `SHA256SUMS.txt`, then publishes it. A clean unauthenticated HTTP client downloads the public asset and verifies its SHA-256. If publication/verification fails, inspect the draft/published Release before retrying; creation intentionally refuses to overwrite an existing transfer. Do not treat a failed command as proof that nothing was uploaded.

Local artifacts, passwords, and private records are kept in `~/.local/state/encrypted-transfers/<transfer-id>/` (directory `0700`, sensitive files `0600`), **outside this checkout**. Never copy this directory into the repository. The tool prints the password file location, not its content. Convey the password separately to the recipient, ideally over an independent trusted channel.

## Retention and deletion

There is no automatic expiration or download-count trigger. An anonymous download count does not prove the intended recipient received it. Delete a specific Release and its tag only after confirmation. Local ciphertext, password and record are retained for recovery; clean them separately when no longer needed. Do not commit payloads, passwords or private transfer inventories: Git history persists even after a file is removed.

## Recipient

1. Download the `.7z` asset and its checksum without signing in to GitHub.
2. Verify SHA-256 against the sender's trusted message/checksum.
3. Open using 7-Zip, enter the separately received password, and extract to a new directory.
4. Confirm receipt and extraction to the sender so the Release can be removed.

## Tests

```sh
python3 -m unittest discover -s tests -v
```
