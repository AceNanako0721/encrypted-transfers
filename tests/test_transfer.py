import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("transfer", Path(__file__).resolve().parents[1] / "transfer.py")
transfer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(transfer)


@unittest.skipUnless(shutil.which("7zz") or shutil.which("7z"), "7-Zip required")
class TransferTests(unittest.TestCase):
    def test_round_trip_git_and_private_exclusions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "synthetic-project"
            source.mkdir()
            (source / "hello.txt").write_text("synthetic Japanese: 日本語\n")
            (source / "empty").mkdir()
            (source / "local-data").mkdir()
            (source / "local-data" / "secret.txt").write_text("not for transfer")
            (source / "local-data" / ".gitkeep").touch()
            (source / ".env").write_text("DUMMY=excluded")
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            subprocess.run(["git", "-C", str(source), "add", "hello.txt"], check=True)
            subprocess.run(["git", "-C", str(source), "-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid", "commit", "-qm", "test"], check=True)
            old = transfer.STATE
            transfer.STATE = root / "private-state"
            try:
                transfer.pack(source)
                out = next(transfer.STATE.iterdir())
                record = json.loads((out / "record.json").read_text())
                self.assertTrue(record["round_trip_verified"])
                self.assertIn(".env", record["excluded"])
                self.assertIn("local-data/secret.txt", record["excluded"])
                self.assertNotIn("local-data/.gitkeep", record["excluded"])
                seven = shutil.which("7zz") or shutil.which("7z")
                extracted = root / "extracted"
                subprocess.run([seven, "x", "-y", "-o" + str(extracted), str(out / (record["id"] + ".7z"))], input=(out / "password.txt").read_bytes(), capture_output=True, check=True)
                self.assertTrue((extracted / "TRANSFER-MANIFEST.json").is_file())
                self.assertTrue((extracted / source.name / "local-data/.gitkeep").is_file())
                self.assertFalse((extracted / source.name / "local-data/secret.txt").exists())
                self.assertFalse((extracted / source.name / ".transfer-manifest.json").exists())
                self.assertEqual((out / "password.txt").stat().st_mode & 0o777, 0o600)
                self.assertEqual(transfer.STATE.stat().st_mode & 0o777, 0o700)
                self.assertFalse(record["published"])
            finally:
                transfer.STATE = old

    def test_tampered_archive_never_reaches_github(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            old = transfer.STATE
            transfer.STATE = Path(tmp)
            tag = "transfer-synthetic"
            out = transfer.state_dir(tag)
            out.mkdir()
            (out / (tag + ".7z")).write_bytes(b"tampered")
            (out / "record.json").write_text(json.dumps({"round_trip_verified": True, "sha256": "incorrect"}))
            try:
                with patch.object(transfer, "run") as remote:
                    with self.assertRaisesRegex(RuntimeError, "changed archive"):
                        transfer.publish(tag)
                    remote.assert_not_called()
            finally:
                transfer.STATE = old

    def test_delete_rejects_unsafe_id_before_remote_call(self):
        from unittest.mock import patch
        with patch.object(transfer, "run") as remote:
            with self.assertRaises(ValueError):
                transfer.delete("../another-release")
            remote.assert_not_called()

    def test_symlink_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "link").symlink_to("/etc/passwd")
            old = transfer.STATE
            transfer.STATE = root / "state"
            try:
                with self.assertRaisesRegex(ValueError, "Symlink"):
                    transfer.pack(source)
            finally:
                transfer.STATE = old

    def test_unsafe_id_refused(self):
        for tag in ["../outside", "transfer-../../x", "", "/tmp/x"]:
            with self.assertRaises(ValueError):
                transfer.state_dir(tag)

    def test_shallow_history_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            origin = root / "origin"
            subprocess.run(["git", "init", "-q", str(origin)], check=True)
            for message in ["first", "second"]:
                subprocess.run(["git", "-C", str(origin), "-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid", "commit", "--allow-empty", "-qm", message], check=True)
            shallow = root / "shallow"
            subprocess.run(["git", "clone", "-q", "--depth=1", origin.as_uri(), str(shallow)], check=True)
            self.assertTrue((shallow / ".git/shallow").exists())
            with self.assertRaisesRegex(ValueError, "Incomplete"):
                transfer.pack(shallow)

    def test_partial_history_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "remote.origin.promisor", "true"], check=True)
            with self.assertRaisesRegex(ValueError, "Partial/promisor"):
                transfer.pack(root)

    def test_linked_worktree_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").write_text("gitdir: /unrelated/path")
            with self.assertRaisesRegex(ValueError, "Linked worktrees"):
                transfer.pack(root)


if __name__ == "__main__":
    unittest.main()
