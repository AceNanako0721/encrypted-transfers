# Repository boundaries

This is a PUBLIC encrypted-transfer tooling repository, not a payload repository.

- Only generic tooling, tests using synthetic data, and public documentation belong in Git.
- Never commit project payloads, passwords, local transfer records, source paths, business names, runtime databases, or private manifests.
- Payload state lives outside this checkout in `~/.local/state/encrypted-transfers/`.
- Never upload plaintext or send passwords to GitHub (including Actions, Issues, Release notes or logs).
- Use AES-256 7z with encrypted headers. Never silently fall back to ZipCrypto.
- Each transfer requires actual round-trip file-hash verification and an anonymous-download SHA-256 check.
- Delete only the specific transfer's Release/tag after the recipient confirms receipt. No download-count-based deletion and no blanket cleanup.
- Stop source writers if an atomic application-level snapshot is required; hashing copied files is not an atomic source snapshot.
- Existing source projects and their Git remotes must remain unchanged.
- For subsequent changes, use a feature/fix branch rather than committing directly on main.
- Validation: `python3 -m unittest discover -s tests -v` and `python3 -m py_compile transfer.py`.
