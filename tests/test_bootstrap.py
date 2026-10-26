import io
import lzma
import shutil
import tarfile
import unittest

from test_create import ProjectFixture
from test_templates import generator, index_row


BUSYBOX = shutil.which("busybox")


class BootstrapTests(ProjectFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        result = self.create()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.archive = self.base / "fixture.tar.xz"
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w", format=tarfile.PAX_FORMAT) as rootfs:
            for directory in ["etc", "usr", "usr/share"]:
                info = tarfile.TarInfo(directory)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                rootfs.addfile(info)
            for name, content in [("etc/resolv.conf", b"nameserver 127.0.0.1\n"),
                                  ("usr/share/file with spaces", b"rootfs content"),
                                  ("usr/share/" + "long-name-" * 20, b"long name")]:
                info = tarfile.TarInfo(name)
                info.size = len(content)
                info.mode = 0o640
                rootfs.addfile(info, io.BytesIO(content))
            link = tarfile.TarInfo("link")
            link.type = tarfile.SYMTYPE
            link.linkname = "usr/share/file with spaces"
            rootfs.addfile(link)
        self.archive.write_bytes(lzma.compress(archive.getvalue()))
        self.env["TEST_ARCHIVE"] = str(self.archive)
        self.env["TEST_BUSYBOX"] = BUSYBOX or ""
        self.stub("docker", '''import json, os, shlex, subprocess, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["TEST_LOG"], "a") as log:
    log.write(json.dumps(["docker"] + args) + "\\n")
if args[:2] == ["image", "inspect"]:
    sys.exit(1 if os.environ.get("TEST_MISSING_IMAGE") else 0)
if args and args[0] == "pull":
    if os.environ.get("TEST_PULL_FAIL"):
        print("simulated registry or platform failure", file=sys.stderr)
        sys.exit(23)
if args and args[0] == "run":
    if os.environ.get("TEST_RUN_FAIL"):
        sys.exit(17)
    if os.environ.get("TEST_EXECUTE"):
        assert args[-4:-1] == ["alpine:latest", "/bin/sh", "-c"]
        script = args[-1]
        mounts = {}
        for i, arg in enumerate(args[:-1]):
            if arg == "-v":
                source, target = args[i + 1].rsplit(":", 1)
                assert source.startswith(os.environ["TEST_BASE"] + "/")
                mounts[target] = source
        assert "/mnt/rootfs" in mounts
        for target, source in mounts.items():
            script = script.replace(target, shlex.quote(source))
        sys.exit(subprocess.run([os.environ["TEST_BUSYBOX"], "sh", "-c", script]).returncode)
''')
        self.stub("wget", '''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
url = args[-1]
with open(os.environ["TEST_LOG"], "a") as log:
    log.write(json.dumps(["wget", url]) + "\\n")
output = Path(args[args.index("-O") + 1])
if url.endswith("/index-system"):
    output.write_bytes(Path(os.environ["TEST_INDEX"]).read_bytes())
elif url.endswith(".tar.xz"):
    output.write_bytes(Path(os.environ["TEST_ARCHIVE"]).read_bytes())
else:
    output.write_bytes(b"test squashfs")
''')
        for tool, failure in [("apk", "TEST_APK_FAIL"), ("unsquashfs", "TEST_UNSQUASHFS_FAIL")]:
            self.stub(tool, f'''import json, os, sys
with open(os.environ["TEST_LOG"], "a") as log:
    log.write(json.dumps([{tool!r}] + sys.argv[1:]) + "\\n")
sys.exit(1 if os.environ.get({failure!r}) else 0)
''')

    def execute_helper(self):
        self.env["TEST_EXECUTE"] = "1"
        for tool in ["tar", "rm", "touch"]:
            (self.bin / tool).symlink_to(BUSYBOX)

    def use_squashfs(self):
        generator.generate(index_row("nixos", "unstable"), self.templates)
        self.index.write_text(index_row("nixos", "unstable"))
        with (self.projects / "demo").open("a") as project:
            project.write('\ntemplate="nixos-unstable"\n')

    def helper_run(self):
        return next(args for args in self.commands() if args[:2] == ["docker", "run"])

    def test_cached_image_is_reused_without_download_or_import(self):
        work = self.base / "work"
        work.mkdir()
        sentinel = work / "keep"
        sentinel.touch()
        result = self.run_function("bootstrap")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commands(), [["docker", "image", "inspect", "alpine:latest"]])
        self.assertTrue(sentinel.exists())

    def test_missing_image_is_pulled_without_changing_work_files(self):
        self.env["TEST_MISSING_IMAGE"] = "1"
        work = self.base / "work"
        work.mkdir()
        (work / "keep").touch()
        result = self.run_function("bootstrap")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commands(), [["docker", "image", "inspect", "alpine:latest"],
                                          ["docker", "pull", "alpine:latest"]])
        self.assertTrue((work / "keep").exists())

    def test_pull_failure_preserves_error_and_stops_init_and_clean(self):
        self.env.update(TEST_MISSING_IMAGE="1", TEST_PULL_FAIL="1")
        for command in ["bootstrap", "init_project", "clean_project"]:
            with self.subTest(command=command):
                if self.log.exists():
                    self.log.unlink()
                result = self.run_function(command, "y\n")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("simulated registry or platform failure", result.stderr)
                self.assertFalse(any(args[0] == "wget" or args[:2] in [["docker", "run"], ["docker", "import"]]
                                     for args in self.commands()))
                self.assertFalse((self.rootfs() / ".buildenv").exists())
                self.assertNotIn("success", result.stdout)
                self.assertNotIn("finish cleanup", result.stdout)
                if command == "init_project":
                    self.assertFalse((self.base / "work").exists())

    def test_tar_init_uses_alpine_sh_and_only_downloads_project_image(self):
        result = self.run_function("init_project")
        self.assertEqual(result.returncode, 0, result.stderr)
        run = self.helper_run()
        self.assertEqual(run[-4:-1], ["alpine:latest", "/bin/sh", "-c"])
        self.assertIn("tar -xf /mnt/tmp/rootfs.tar", run[-1])
        self.assertNotIn("apk", run[-1])
        self.assertEqual(len([args for args in self.commands() if args[0] == "wget"]), 2)
        self.assertFalse(any(args[:2] == ["docker", "import"] for args in self.commands()))

    @unittest.skipUnless(BUSYBOX, "BusyBox is needed to execute the helper shell offline")
    def test_busybox_extracts_tar_links_long_names_and_permissions(self):
        self.execute_helper()
        result = self.run_function("init_project")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rootfs = self.rootfs()
        file = rootfs / "usr/share/file with spaces"
        self.assertEqual(file.read_bytes(), b"rootfs content")
        self.assertEqual(file.stat().st_mode & 0o777, 0o640)
        self.assertTrue((rootfs / "link").is_symlink())
        self.assertEqual((rootfs / "link").read_bytes(), b"rootfs content")
        self.assertTrue((rootfs / ("usr/share/" + "long-name-" * 20)).exists())
        self.assertFalse((rootfs / "etc/resolv.conf").exists())
        self.assertTrue((rootfs / ".buildenv").exists())

    @unittest.skipUnless(BUSYBOX, "BusyBox is needed to execute the helper shell offline")
    def test_bad_tar_does_not_create_success_marker(self):
        self.execute_helper()
        self.archive.write_bytes(lzma.compress(b"invalid tar archive"))
        result = self.run_function("init_project")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.rootfs() / ".buildenv").exists())
        self.assertNotIn("init project demo success", result.stdout)

    @unittest.skipUnless(BUSYBOX, "BusyBox is needed to execute the helper shell offline")
    def test_squashfs_uses_apk_and_stops_before_marking_failures(self):
        self.execute_helper()
        self.use_squashfs()
        for failure in ["TEST_APK_FAIL", "TEST_UNSQUASHFS_FAIL"]:
            with self.subTest(failure=failure):
                self.env[failure] = "1"
                self.log.unlink(missing_ok=True)
                result = self.run_function("init_project")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.rootfs() / ".buildenv").exists())
                self.assertIn(["apk", "add", "--no-cache", "squashfs-tools"], self.commands())
                if failure == "TEST_APK_FAIL":
                    self.assertFalse(any(args[0] == "unsquashfs" for args in self.commands()))
                self.env.pop(failure)
        result = self.run_function("init_project")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.rootfs() / ".buildenv").exists())

    @unittest.skipUnless(BUSYBOX, "BusyBox is needed to execute the helper shell offline")
    def test_cleanup_removes_hidden_and_special_names_preserving_root_and_link_targets(self):
        self.execute_helper()
        rootfs = self.rootfs()
        inode = rootfs.stat().st_ino
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "keep").touch()
        for name in ["normal", ".hidden", "..double-dot", "space name", "line\nbreak", "quote'\"", "-rf", ".buildenv"]:
            (rootfs / name).touch()
        (rootfs / "nested").mkdir()
        (rootfs / "nested/file").touch()
        (rootfs / "directory link").symlink_to(outside, target_is_directory=True)
        (rootfs / "dangling link").symlink_to(self.base / "missing")
        result = self.run_function("clean_project", "y\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(rootfs.stat().st_ino, inode)
        self.assertEqual(list(rootfs.iterdir()), [])
        self.assertTrue((outside / "keep").exists())
        self.assertEqual(self.helper_run()[-4:-1], ["alpine:latest", "/bin/sh", "-c"])
        self.assertEqual(self.run_function("clean_project", "y\n").returncode, 0)

    def test_container_failures_are_reported_without_success(self):
        self.env["TEST_RUN_FAIL"] = "1"
        for command in ["init_project", "clean_project"]:
            with self.subTest(command=command):
                result = self.run_function(command, "y\n")
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("success", result.stdout)
                self.assertNotIn("finish cleanup", result.stdout)
                self.assertFalse((self.rootfs() / ".buildenv").exists())

    @unittest.skipUnless(BUSYBOX, "BusyBox is needed to execute the helper shell offline")
    def test_filesystem_cleanup_failure_propagates(self):
        self.execute_helper()
        (self.bin / "rm").unlink()
        self.stub("rm", 'import sys\nprint("simulated delete failure", file=sys.stderr)\nsys.exit(1)\n')
        (self.rootfs() / "keep").touch()
        result = self.run_function("clean_project", "y\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("simulated delete failure", result.stderr)
        self.assertNotIn("finish cleanup", result.stdout)
        self.assertTrue((self.rootfs() / "keep").exists())

    def test_cancelled_cleanup_does_not_run_helper(self):
        result = self.run_function("clean_project", "n\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("canceled cleaning", result.stdout)
        self.assertFalse(any(args[:2] == ["docker", "run"] for args in self.commands()))


if __name__ == "__main__":
    unittest.main()
