import io
import lzma
from pathlib import PurePosixPath
import shlex
import shutil
import subprocess
import tarfile
import unittest

from test_create import ProjectFixture, ROOT
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

    def add_archive_entries(self, files=None, links=None):
        files, links = files or {}, links or {}
        contents = io.BytesIO(lzma.decompress(self.archive.read_bytes()))
        output = io.BytesIO()
        with tarfile.open(fileobj=contents) as source, tarfile.open(fileobj=output, mode="w") as target:
            names = set()
            for entry in source:
                target.addfile(entry, source.extractfile(entry) if entry.isfile() else None)
                names.add(entry.name)
            parents = {str(parent) for name in files | links for parent in PurePosixPath(name).parents}
            for name in sorted(parents - names - links.keys() - {"."}, key=lambda name: (name.count("/"), name)):
                entry = tarfile.TarInfo(name)
                entry.type, entry.mode = tarfile.DIRTYPE, 0o755
                target.addfile(entry)
            for name, content in files.items():
                entry = tarfile.TarInfo(name)
                data = content.encode()
                entry.size, entry.mode = len(data), 0o644
                target.addfile(entry, io.BytesIO(data))
            for name, destination in links.items():
                entry = tarfile.TarInfo(name)
                entry.type, entry.linkname = tarfile.SYMTYPE, destination
                target.addfile(entry)
        self.archive.write_bytes(lzma.compress(output.getvalue()))

    def add_systemd(self, target="/usr/lib/systemd/systemd", merged=False):
        links = {"usr/sbin/init" if merged else "sbin/init": target}
        if merged:
            links["sbin"] = "usr/sbin"
        self.add_archive_entries({"usr/lib/systemd/systemd": "systemd binary"}, links)

    def run_setup(self):
        script = subprocess.check_output([
            "bash", "-c", 'source "$1" help >/dev/null; DISTRO_INIT=/sbin/init; rootfs_setup_script',
            "bash", str(ROOT / "buildenv"),
        ], env=self.env, text=True)
        return subprocess.run([BUSYBOX, "sh", "-c", script.replace("/mnt/rootfs", shlex.quote(str(self.rootfs())))],
                              env=self.env, capture_output=True, text=True)

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
    def test_systemd_cleanup_preserves_loopback_links_and_unrelated_files(self):
        self.execute_helper()
        self.add_systemd()
        removed = [
            "etc/systemd/network/eth0.network", "etc/systemd/network/br0.netdev",
            "etc/systemd/network/eth0.network.d/override.conf",
            "etc/systemd/network/br0.netdev.d/override.conf",
            "etc/NetworkManager/system-connections/wired.nmconnection",
            "etc/NetworkManager/system-connections/.hidden-profile",
            "etc/netplan/10-dhcp.yaml", "etc/netplan/custom.yml",
            "etc/network/interfaces.d/eth0",
            "etc/sysconfig/network-scripts/ifcfg-eth0", "etc/sysconfig/network-scripts/route-eth0",
            "etc/sysconfig/network/ifcfg-eth0", "etc/sysconfig/network/ifroute-eth0",
        ]
        kept = [
            "etc/systemd/network/10-custom.link", "etc/systemd/network/10-custom.link.d/override.conf",
            "etc/NetworkManager/conf.d/10-unrelated.conf", "etc/netplan/README",
            "etc/sysconfig/network-scripts/ifcfg-lo", "etc/sysconfig/network/ifcfg-lo",
            "etc/cloud/cloud.cfg", "etc/cloud/cloud.cfg.d/10-unrelated.cfg",
        ]
        self.add_archive_entries(dict.fromkeys(removed + kept, "original configuration") | {
            "etc/network/interfaces": "auto eth0\niface eth0 inet dhcp\n",
            "etc/dhcpcd.conf": "dhcp options", "etc/dhcpcd/dhcpcd.conf": "dhcp options",
        })
        result = self.run_function("init_project")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rootfs = self.rootfs()
        for name in removed:
            self.assertFalse((rootfs / name).exists(), name)
        for name in kept:
            self.assertEqual((rootfs / name).read_text(), "original configuration", name)
        self.assertIn("Unmanaged=yes", (rootfs / "etc/systemd/network/00-buildenv.network").read_text())
        nm = (rootfs / "etc/NetworkManager/conf.d/99-buildenv.conf").read_text()
        for value in ["no-auto-default=*", "dns=none", "unmanaged-devices=*"]:
            self.assertIn(value, nm)
        self.assertEqual((rootfs / "etc/network/interfaces").read_text(),
                         "auto lo\niface lo inet loopback\niface lo inet6 loopback\n")
        self.assertIn("config: disabled", (rootfs / "etc/cloud/cloud.cfg.d/99-buildenv-network.cfg").read_text())
        for name in ["etc/dhcpcd.conf", "etc/dhcpcd/dhcpcd.conf"]:
            self.assertEqual((rootfs / name).read_text(), "denyinterfaces *\n")
        self.assertTrue((rootfs / ".buildenv").exists())

    @unittest.skipUnless(BUSYBOX, "BusyBox is needed to execute the helper shell offline")
    def test_systemd_detection_handles_absolute_relative_and_usrmerged_init_links(self):
        self.execute_helper()
        original = self.archive.read_bytes()
        for destination, merged in [("/usr/lib/systemd/systemd", False),
                                    ("/lib/systemd/systemd", True),
                                    ("../usr/lib/systemd/systemd", False),
                                    ("../lib/systemd/systemd", True)]:
            with self.subTest(destination=destination, merged=merged):
                shutil.rmtree(self.rootfs())
                self.rootfs().mkdir()
                self.archive.write_bytes(original)
                self.add_systemd(destination, merged)
                if destination == "/lib/systemd/systemd":
                    self.add_archive_entries(links={"lib": "usr/lib"})
                result = self.run_function("init_project")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue((self.rootfs() / "etc/systemd/network/00-buildenv.network").exists())

    @unittest.skipUnless(BUSYBOX, "BusyBox is needed to execute the helper shell offline")
    def test_non_systemd_init_preserves_network_configuration_even_with_systemd_installed(self):
        self.execute_helper()
        self.add_archive_entries({"usr/lib/systemd/systemd": "systemd binary", "sbin/openrc-init": "OpenRC",
                                  "etc/systemd/network/eth0.network": "DHCP=yes",
                                  "etc/network/interfaces": "iface eth0 inet dhcp"},
                                 {"sbin/init": "openrc-init"})
        result = self.run_function("init_project")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rootfs = self.rootfs()
        self.assertEqual((rootfs / "etc/systemd/network/eth0.network").read_text(), "DHCP=yes")
        self.assertEqual((rootfs / "etc/network/interfaces").read_text(), "iface eth0 inet dhcp")
        self.assertFalse((rootfs / "etc/NetworkManager").exists())
        self.assertFalse((rootfs / "etc/resolv.conf").exists())

    @unittest.skipUnless(BUSYBOX, "BusyBox is needed to execute the helper shell offline")
    def test_custom_init_path_and_installed_tools_without_configuration(self):
        self.execute_helper()
        init_path = "/custom path/init's name"
        with (self.templates / "debian-bookworm").open("a") as template:
            template.write(f"\nDISTRO_INIT={shlex.quote(init_path)}\n")
        self.add_archive_entries({
            init_path.lstrip("/"): "systemd binary", "usr/lib/systemd/systemd": "systemd binary",
            "usr/bin/cloud-init": "cloud-init", "usr/sbin/dhcpcd": "dhcpcd",
        })
        result = self.run_function("init_project")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rootfs = self.rootfs()
        self.assertIn("Unmanaged=yes", (rootfs / "etc/systemd/network/00-buildenv.network").read_text())
        self.assertEqual((rootfs / "etc/dhcpcd.conf").read_text(), "denyinterfaces *\n")
        self.assertIn("config: disabled", (rootfs / "etc/cloud/cloud.cfg.d/99-buildenv-network.cfg").read_text())

    @unittest.skipUnless(BUSYBOX, "BusyBox is needed to execute the helper shell offline")
    def test_setup_is_idempotent_with_missing_optional_configuration(self):
        self.execute_helper()
        self.add_systemd()
        result = self.run_function("init_project")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rootfs = self.rootfs()
        original = {str(path.relative_to(rootfs)): path.read_bytes() for path in rootfs.rglob("*") if path.is_file()}
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(original, {str(path.relative_to(rootfs)): path.read_bytes()
                                    for path in rootfs.rglob("*") if path.is_file()})
        for name in ["cloud", "dhcpcd", "network", "netplan", "sysconfig"]:
            self.assertFalse((rootfs / "etc" / name).exists())

    @unittest.skipUnless(BUSYBOX, "BusyBox is needed to execute the helper shell offline")
    def test_config_directory_and_leaf_symlinks_stay_inside_rootfs(self):
        self.execute_helper()
        self.add_systemd()
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "keep").write_text("outside sentinel")
        self.add_archive_entries({"etc/preserved": "inside sentinel"}, {
            "etc/systemd/network": "/var/network",
            "etc/NetworkManager/conf.d": str(outside),
            "var/network/00-buildenv.network": "/etc/preserved",
            "etc/resolv.conf": str(outside / "keep"),
            ".buildenv": str(outside / "keep"),
        })
        result = self.run_function("init_project")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rootfs = self.rootfs()
        self.assertIn("Unmanaged=yes", (rootfs / "var/network/00-buildenv.network").read_text())
        self.assertTrue((rootfs / str(outside).lstrip("/") / "99-buildenv.conf").exists())
        self.assertEqual((rootfs / "etc/preserved").read_text(), "inside sentinel")
        self.assertEqual(list(outside.iterdir()), [outside / "keep"])
        self.assertEqual((outside / "keep").read_text(), "outside sentinel")
        self.assertFalse((rootfs / "etc/resolv.conf").is_symlink())
        self.assertFalse((rootfs / ".buildenv").is_symlink())

    @unittest.skipUnless(BUSYBOX, "BusyBox is needed to execute the helper shell offline")
    def test_config_write_failure_does_not_mark_rootfs_ready(self):
        self.execute_helper()
        self.add_systemd()
        self.add_archive_entries({"etc/NetworkManager/conf.d/99-buildenv.conf/keep": "blocks config write"})
        result = self.run_function("init_project")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("configuration failed", result.stderr)
        self.assertFalse((self.rootfs() / ".buildenv").exists())
        self.assertNotIn("init project demo success", result.stdout)

    @unittest.skipUnless(BUSYBOX, "BusyBox is needed to execute the helper shell offline")
    def test_symlink_loop_fails_without_marking_rootfs_ready(self):
        self.execute_helper()
        self.add_archive_entries(links={"sbin/init": "init"})
        result = self.run_function("init_project")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Too many rootfs symlinks", result.stderr)
        self.assertFalse((self.rootfs() / ".buildenv").exists())

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
