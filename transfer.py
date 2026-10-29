#!/usr/bin/env python3
"""Encrypted, manually retired GitHub Release transfers (stdlib + 7-Zip + gh)."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import urllib.request

REPO = "AceNanako0721/encrypted-transfers"
STATE = Path.home() / ".local/state/encrypted-transfers"
SKIP_DIRS = {"__pycache__", ".venv", "venv", "node_modules", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
SKIP_NAMES = {".env", "settings.json", "secrets.json", ".DS_Store"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".log", ".sqlite", ".sqlite3", ".db"}


def run(args, **kw):
    return subprocess.run(args, check=True, capture_output=True, **kw)


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def snapshot(root):
    return {str(f.relative_to(root)): sha(f) for f in sorted(root.rglob("*")) if f.is_file()}


def save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def state_dir(tag):
    if not tag.startswith("transfer-") or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in tag):
        raise ValueError("Invalid transfer ID")
    return STATE / tag


def assert_complete_git(root):
    git = root / ".git"
    if not git.exists():
        return
    if not git.is_dir():
        raise ValueError("Linked worktrees require a standalone clone before packaging")
    for marker in ["shallow", "commondir", "objects/info/alternates", "info/grafts"]:
        if (git / marker).exists():
            raise ValueError("Incomplete or external Git history: " + marker)
    if any((git / "objects/pack").glob("*.promisor")):
        raise ValueError("Partial/promisor Git history is not supported")
    result = subprocess.run(["git", "-C", str(root), "config", "--local", "--get-regexp", r"^(extensions\.partialclone|remote\..*\.promisor|remote\..*\.partialclonefilter)$"], capture_output=True)
    if result.returncode == 0:
        raise ValueError("Partial/promisor Git configuration is not supported")
    if result.returncode != 1:
        raise RuntimeError("Cannot verify Git configuration")
    env = dict(os.environ, GIT_NO_LAZY_FETCH="1")
    run(["git", "-C", str(root), "fsck", "--full"], env=env)


def pack(source):
    source = Path(source).resolve(strict=True)
    if not source.is_dir():
        raise ValueError("Source must be a directory")
    assert_complete_git(source)
    seven = shutil.which("7zz") or shutil.which("7z")
    if not seven:
        raise RuntimeError("Install official 7-Zip first")
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE.chmod(0o700)
    tag = "transfer-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ").lower() + "-" + secrets.token_hex(4)
    out = state_dir(tag)
    out.mkdir(mode=0o700)
    password = secrets.token_urlsafe(32)
    password_file = out / "password.txt"
    password_file.write_text(password + "\n")
    password_file.chmod(0o600)
    skipped = []
    with tempfile.TemporaryDirectory(prefix="encrypted-transfer-") as tmp:
        base = Path(tmp)
        stage = base / "stage" / source.name
        def ignore(directory, names):
            rel = Path(directory).relative_to(source)
            result = []
            for name in names:
                f = Path(directory) / name
                # Preserve .git byte-for-byte; runtime exclusions apply only outside it.
                in_git = rel.parts and rel.parts[0] == ".git"
                runtime_content = "local-data" in rel.parts and name != ".gitkeep"
                if not in_git and (runtime_content or name in SKIP_DIRS or name in SKIP_NAMES or name.startswith(".env.") or f.suffix.lower() in SKIP_SUFFIXES):
                    skipped.append(str(rel / name))
                    result.append(name)
                elif f.is_symlink():
                    raise ValueError("Symlink requires explicit review: " + str(rel / name))
            return result
        shutil.copytree(source, stage, ignore=ignore)
        manifest = snapshot(stage)
        save(stage.parent / "TRANSFER-MANIFEST.json", {"files": manifest, "excluded": skipped})
        archive = out / (tag + ".7z")
        run([seven, "a", "-t7z", "-mhe=on", "-mx=5", "-p", str(archive), source.name, "TRANSFER-MANIFEST.json"], cwd=stage.parent, input=(password + "\n").encode())
        # Empty/wrong passwords must not reveal file names.
        bad = subprocess.run([seven, "l", str(archive)], input=b"incorrect-password\n", capture_output=True)
        if bad.returncode == 0 or source.name.encode() in bad.stdout:
            raise RuntimeError("Archive header encryption check failed")
        extracted = base / "verify"
        run([seven, "x", "-y", "-o" + str(extracted), str(archive)], input=(password + "\n").encode())
        restored = extracted / source.name
        check = snapshot(restored)
        if json.loads((extracted / "TRANSFER-MANIFEST.json").read_text())["files"] != manifest:
            raise RuntimeError("Encrypted manifest verification failed")
        if check != manifest:
            raise RuntimeError("Round-trip file hash verification failed")
        assert_complete_git(restored)
    archive.chmod(0o600)
    digest = sha(archive)
    checksum = out / "SHA256SUMS.txt"
    checksum.write_text(digest + "  " + archive.name + "\n")
    save(out / "record.json", {"id": tag, "repo": REPO, "source": str(source), "file_count": len(manifest), "excluded": skipped, "sha256": digest, "bytes": archive.stat().st_size, "round_trip_verified": True, "published": False})
    print(json.dumps({"id": tag, "files": len(manifest), "bytes": archive.stat().st_size, "excluded": skipped, "password_file": str(password_file), "round_trip_verified": True}, ensure_ascii=False))


def publish(tag):
    out = state_dir(tag)
    record = json.loads((out / "record.json").read_text())
    archive = out / (tag + ".7z")
    if not record.get("round_trip_verified") or sha(archive) != record["sha256"]:
        raise RuntimeError("Unverified or changed archive")
    run(["gh", "release", "create", tag, str(archive), str(out / "SHA256SUMS.txt"), "--repo", REPO, "--draft", "--title", tag, "--notes", "Encrypted temporary transfer. Password is distributed separately. Verify SHA256SUMS.txt before extraction. Removed manually after recipient confirmation."])
    run(["gh", "release", "edit", tag, "--repo", REPO, "--draft=false", "--latest=false"])
    metadata = json.loads(run(["gh", "release", "view", tag, "--repo", REPO, "--json", "url,assets"], text=True).stdout)
    url = next(x["url"] for x in metadata["assets"] if x["name"] == archive.name)
    # urllib has no gh credentials, browser cookies, or authorization headers.
    with tempfile.TemporaryDirectory(prefix="transfer-anonymous-") as tmp:
        downloaded = Path(tmp) / "download.7z"
        with urllib.request.urlopen(url, timeout=120) as response, downloaded.open("wb") as f:
            if response.status != 200:
                raise RuntimeError("Anonymous download failed")
            shutil.copyfileobj(response, f)
        if sha(downloaded) != record["sha256"]:
            raise RuntimeError("Anonymous download SHA-256 mismatch")
    record.update(published=True, url=url, release_url=metadata["url"], anonymous_download_verified=True)
    save(out / "record.json", record)
    print(json.dumps({k: record[k] for k in ["id", "url", "release_url", "sha256", "bytes", "anonymous_download_verified"]}))


def delete(tag):
    out = state_dir(tag)
    record_path = out / "record.json"
    if not record_path.is_file():
        raise ValueError("Refusing to delete an unregistered transfer")
    record = json.loads(record_path.read_text())
    if record.get("id") != tag or record.get("repo") != REPO:
        raise ValueError("Transfer record identity mismatch")
    run(["gh", "release", "delete", tag, "--repo", REPO, "--cleanup-tag", "--yes"])
    remaining = json.loads(run(["gh", "api", f"repos/{REPO}/releases", "--paginate", "--slurp"], text=True).stdout)
    if any(r["tag_name"] == tag for page in remaining for r in page):
        raise RuntimeError("Release still exists")
    record_path = out / "record.json"
    if record_path.exists():
        record = json.loads(record_path.read_text())
        record["deleted"] = dt.datetime.now(dt.timezone.utc).isoformat()
        save(record_path, record)
    print("Release and tag deleted; local encrypted archive/password retained for recovery.")


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("pack").add_argument("source")
    sub.add_parser("publish").add_argument("id")
    sub.add_parser("delete").add_argument("id")
    sub.add_parser("list")
    args = parser.parse_args()
    if args.command == "pack":
        pack(args.source)
    elif args.command == "publish":
        publish(args.id)
    elif args.command == "delete":
        delete(args.id)
    else:
        result = run(["gh", "release", "list", "--repo", REPO], text=True)
        print(result.stdout, end="")


if __name__ == "__main__":
    main()
