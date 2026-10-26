import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest

from test_templates import ROOT, generator, index_row


class ProjectFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="buildenv-create-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.config = self.base / "config with spaces/buildenv"
        self.templates = self.config / "templates"
        self.projects = self.config / "projects"
        self.index = self.base / "index-system"
        self.index.write_text(index_row("debian", "bookworm"))
        generator.generate(self.index.read_text(), self.templates)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.log = self.base / "commands.jsonl"
        self.env = os.environ.copy()
        self.env.pop("XDG_DATA_HOME", None)
        self.env.update(HOME=str(self.base), XDG_CONFIG_HOME=str(self.config.parent),
                        PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        TEST_LOG=str(self.log), TEST_INDEX=str(self.index),
                        TEST_BASE=str(self.base))
        self.stub("uname", 'print("x86_64")\n')
        self.stub("column", 'import sys\nsys.stdout.write(sys.stdin.read())\n')
        self.stub("docker", '''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
log_path = Path(os.environ["TEST_LOG"])
previous = [json.loads(line) for line in log_path.read_text().splitlines()] if log_path.exists() else []
with log_path.open("a") as log:
    log.write(json.dumps(["docker"] + args) + "\\n")
if args and args[0] == "ps":
    if not os.environ.get("TEST_NEW_CONTAINER") or any(row[:2] == ["docker", "run"] for row in previous):
        print("test-container")
''')
        self.stub("wget", '''import json, lzma, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["TEST_LOG"], "a") as log:
    log.write(json.dumps(["wget", args[-1]]) + "\\n")
output = Path(args[args.index("-O") + 1])
output.write_bytes(Path(os.environ["TEST_INDEX"]).read_bytes() if args[-1].endswith("/index-system") else lzma.compress(b"test rootfs"))
''')

    def stub(self, name, body):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n{body}")
        path.chmod(0o755)

    def run_cli(self, args, input=""):
        return subprocess.run([str(ROOT / "buildenv"), *args], input=input, text=True,
                              capture_output=True, cwd=self.base, env=self.env, timeout=10)

    def create(self, input="\n", name="demo"):
        return self.run_cli(["create"] + ([name] if name is not None else []), input)

    def rootfs(self, name="demo"):
        return Path(self.env.get("XDG_DATA_HOME", self.base / ".local/share")) / "buildenv/rootfs" / name

    def load_project(self, name="demo"):
        output = subprocess.check_output([
            "bash", "-c", 'source "$1"; printf "%s\\0" "$name" "$template" "$rootfs_dir"',
            "bash", str(self.projects / name),
        ], cwd=self.base, env=self.env)
        return [value.decode() for value in output.split(b"\0")[:-1]]

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def assert_no_partial_project(self):
        self.assertFalse((self.projects / "demo").exists())
        self.assertEqual(list(self.projects.glob(".create*")), [])

    def run_function(self, name, input=""):
        work = self.base / "work"
        work.mkdir(exist_ok=True)
        return subprocess.run([
            "bash", "-c", 'source "$1" help >/dev/null; tmp_dir="$2"; "$3" demo',
            "bash", str(ROOT / "buildenv"), str(work), name,
        ], input=input, text=True, capture_output=True, cwd=self.base, env=self.env, timeout=10)

    def start_create(self):
        process = subprocess.Popen([str(ROOT / "buildenv"), "create", "demo"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, cwd=self.base, env=self.env,
                                   start_new_session=True)
        self.addCleanup(self.stop_process, process)
        process.stdin.write(b"\n")
        process.stdin.flush()
        return process

    @staticmethod
    def stop_process(process):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
        process.communicate(timeout=10)

    def wait_for_file(self, path):
        deadline = time.monotonic() + 5
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(path.exists(), f"Timed out waiting for {path}")

    def hold_publication(self):
        self.stub("ln", '''import os, sys, time
from pathlib import Path
base = Path(os.environ["TEST_BASE"])
(base / "ready").touch()
while not (base / "release").exists():
    time.sleep(0.01)
os.execv("/usr/bin/ln", ["ln"] + sys.argv[1:])
''')

class CreateTests(ProjectFixture, unittest.TestCase):
    def test_default_creation_is_offline_and_listable(self):
        result = self.create()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.load_project(), ["demo", "debian-bookworm", str(self.rootfs())])
        self.assertTrue(self.rootfs().is_dir())
        self.assertEqual(list(self.rootfs().iterdir()), [])
        self.assertEqual(stat.S_IMODE((self.projects / "demo").stat().st_mode), 0o644)
        self.assertIn("# extra_option=", (self.projects / "demo").read_text())
        self.assertIn("buildenv init demo", result.stdout)
        self.assertEqual(list(self.projects.glob(".create*")), [])
        listing = self.run_cli(["list"])
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertIn(f"demo:debian:bookworm:{self.rootfs()}", listing.stdout)
        self.assertEqual(self.commands(), [])

    def test_bundled_example_loads_from_configuration_path_with_spaces(self):
        self.projects.mkdir()
        shutil.copyfile(ROOT / "projects/project", self.projects / "example")
        listing = self.run_cli(["list"])
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertEqual(listing.stderr, "")
        self.assertIn("example:debian:bookworm:", listing.stdout)

    def test_interactive_name_retries_and_boundary_lengths(self):
        result = self.create("\nBad\n../bad\n-bad\nbad-\n" + "a" * 64 + "\n" + "a" * 63 + "\n\n", name=None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.projects / ("a" * 63)).exists())
        self.assertGreaterEqual(result.stderr.count("Project name must be"), 6)
        single = self.create(name="a")
        self.assertEqual(single.returncode, 0, single.stderr)

    def test_invalid_command_names_and_extra_arguments(self):
        for name in ["", "Bad", "../bad", "bad_name", "-bad", "bad-", "a" * 64]:
            with self.subTest(name=name):
                result = self.create(name=name)
                self.assertNotEqual(result.returncode, 0)
        result = self.run_cli(["create", "one", "two"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Usage: buildenv create [PROJECT]", result.stderr)
        self.assertFalse(self.projects.exists())

    def test_conflicting_files_directories_and_dangling_symlinks(self):
        self.projects.mkdir()
        (self.projects / "demo").write_text("original")
        result = self.create()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.projects / "demo").read_text(), "original")
        (self.projects / "directory").mkdir()
        (self.projects / "link").symlink_to(self.base / "missing")
        for name in ["directory", "link"]:
            self.assertNotEqual(self.create(name=name).returncode, 0)
        retry = self.create("demo\nother\n\n", name=None)
        self.assertEqual(retry.returncode, 0, retry.stderr)
        self.assertTrue((self.projects / "other").exists())

    def test_grouped_menus_accept_numbers_names_and_retry(self):
        generator.generate(index_row("alpine", "edge") + index_row("debian", "trixie")
                           + index_row("debian", "trixie", variant="cloud"), self.templates)
        result = self.create("invalid\ndebian\n99\n2\ninvalid\n1\n\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.load_project()[1], "debian-trixie-cloud")
        self.assertEqual(result.stderr.count("Invalid selection"), 3)
        result = self.create("2\nbookworm\n\n", name="second")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.load_project("second")[1], "debian-bookworm")

    def test_filters_architecture_vm_and_legacy_templates(self):
        generator.generate(index_row("armonly", "1", arch="arm64") + index_row("netbsd", "11.0"), self.templates)
        (self.templates / "debian-11").write_text('DISTRO_NAME=legacy\nDISTRO_VERSION=11\n')
        (self.templates / "ubuntu-12").write_text('DISTRO_NAME=legacy\nDISTRO_VERSION=12\n')
        result = self.create()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("armonly", result.stderr)
        self.assertNotIn("netbsd", result.stderr)
        self.assertNotIn("legacy", result.stderr)
        self.assertEqual(self.load_project()[1], "debian-bookworm")

    def test_custom_template_defaults_and_alias_selection(self):
        (self.templates / "debian-bookworm").write_text('DISTRO_NAME=custom\nDISTRO_VERSION=1\nDISTRO_INIT=/sbin/init\n')
        shutil.copyfile(self.templates / "debian-bookworm", self.templates / "alias")
        result = self.create("alias\n\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.load_project()[1], "alias")

    def test_no_compatible_templates(self):
        (self.templates / "debian-bookworm").unlink()
        generator.generate(index_row("netbsd", "11.0"), self.templates)
        result = self.create()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No compatible container templates", result.stderr)
        self.assertFalse(self.projects.exists())
        self.assertEqual(self.commands(), [])

    def test_path_normalization_and_xdg_data_directory(self):
        for name, input_path, expected in [
            ("relative", "some dir/../rootfs space", self.base / "rootfs space"),
            ("tilde", "~/tilde rootfs", self.base / "tilde rootfs"),
            ("absolute", str(self.base / "absolute rootfs"), self.base / "absolute rootfs"),
        ]:
            with self.subTest(name=name):
                result = self.create(input_path + "\n", name=name)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.load_project(name)[2], str(expected))
        self.env["XDG_DATA_HOME"] = str(self.base / "custom data")
        result = self.create()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.load_project()[2], str(self.rootfs()))

    def test_shell_metacharacters_are_literal_and_list_safe(self):
        path = self.base / 'space $(touch PWNED) `touch PWNED` $HOME %s "quoted" \\path'
        result = self.create(str(path) + "\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.load_project()[2], str(path))
        self.assertFalse((self.base / "PWNED").exists())
        self.assertIn(str(path), self.run_cli(["list"]).stdout)

    def test_invalid_rootfs_paths_retry_and_existing_empty_directory_survives(self):
        file = self.base / "file"
        file.touch()
        nonempty = self.base / "nonempty"
        nonempty.mkdir()
        (nonempty / ".hidden").touch()
        empty = self.base / "empty"
        empty.mkdir()
        result = self.create(f"{file}\n{nonempty}\nbad:path\nbad\rpath\n{empty}\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.load_project()[2], str(empty))
        self.assertTrue((nonempty / ".hidden").exists())
        self.assertFalse(self.rootfs().exists())

    def test_newline_filename_does_not_make_a_directory_appear_empty(self):
        nonempty = self.base / "nonempty"
        nonempty.mkdir()
        (nonempty / "\n").touch()
        result = self.create(str(nonempty) + "\n\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Rootfs directory must be empty", result.stderr)
        self.assertEqual(self.load_project()[2], str(self.rootfs()))

    def test_newline_in_default_path_is_rejected(self):
        self.env["XDG_DATA_HOME"] = str(self.base / "bad\npath")
        result = self.create("\n" + str(self.base / "valid") + "\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("colons or newlines", result.stderr)
        self.assertEqual(self.load_project()[2], str(self.base / "valid"))

    def test_eof_before_name_or_path_leaves_no_project(self):
        for name in [None, "demo"]:
            result = self.create("", name=name)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Creation canceled", result.stderr)
            self.assertFalse(self.projects.exists())
            self.assertFalse(self.rootfs().exists())

    def test_eof_during_menu_leaves_no_project(self):
        generator.generate(index_row("alpine", "edge"), self.templates)
        result = self.create("")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.projects.exists())

    def test_publication_failure_rolls_back_only_new_rootfs(self):
        self.stub("ln", "import sys\nsys.exit(1)\n")
        result = self.create()
        self.assertNotEqual(result.returncode, 0)
        self.assert_no_partial_project()
        self.assertFalse(self.rootfs().exists())
        self.rootfs().mkdir()
        result = self.create()
        self.assertNotEqual(result.returncode, 0)
        self.assert_no_partial_project()
        self.assertTrue(self.rootfs().is_dir())

    def test_configuration_write_failure_leaves_no_rootfs(self):
        self.stub("chmod", "import sys\nsys.exit(1)\n")
        result = self.create()
        self.assertNotEqual(result.returncode, 0)
        self.assert_no_partial_project()
        self.assertFalse(self.rootfs().exists())

    def test_sigint_removes_partial_configuration_and_new_rootfs(self):
        self.hold_publication()
        process = self.start_create()
        self.wait_for_file(self.base / "ready")
        os.killpg(process.pid, signal.SIGINT)
        _, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 130, stderr.decode())
        self.assert_no_partial_project()
        self.assertFalse(self.rootfs().exists())

    def test_concurrent_same_name_creation_keeps_winner_and_rootfs(self):
        self.hold_publication()
        first = self.start_create()
        self.wait_for_file(self.base / "ready")
        second = self.create()
        self.assertNotEqual(second.returncode, 0)
        (self.base / "release").touch()
        _, stderr = first.communicate(timeout=10)
        self.assertEqual(first.returncode, 0, stderr.decode())
        self.assertTrue(self.rootfs().is_dir())
        self.assertEqual(self.load_project()[0], "demo")
        self.assertEqual(list(self.projects.glob(".create*")), [])

    def test_publish_race_does_not_replace_external_project(self):
        self.stub("ln", '''import os, sys
from pathlib import Path
Path(sys.argv[-1]).write_text("external project")
os.execv("/usr/bin/ln", ["ln"] + sys.argv[1:])
''')
        result = self.create()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.projects / "demo").read_text(), "external project")
        self.assertEqual(list(self.projects.glob(".create*")), [])

    def test_created_paths_remain_single_mount_arguments(self):
        rootfs = self.base / "rootfs with spaces"
        self.assertEqual(self.create(str(rootfs) + "\n").returncode, 0)
        self.assertEqual(self.commands(), [])
        initialized = self.run_function("init_project")
        self.assertEqual(initialized.returncode, 0, initialized.stdout + initialized.stderr)
        extraction = next(args for args in self.commands() if args[:2] == ["docker", "run"])
        self.assertIn(f"{rootfs}:/mnt/rootfs", extraction)
        self.log.unlink()
        (rootfs / ".buildenv").touch()
        for directory in ["usr", "device", "run"]:
            (rootfs / directory).mkdir()
        with (self.projects / "demo").open("a") as config:
            config.write('\nvolume=(-v /source:/workspace -v /other:/other)\nextra_option="--network host\n--label test=yes"\n')
        self.env["TEST_NEW_CONTAINER"] = "1"
        started = self.run_function("start_project")
        self.assertEqual(started.returncode, 0, started.stdout + started.stderr)
        run = next(args for args in self.commands() if args[:2] == ["docker", "run"])
        self.assertIn(f"{rootfs}/usr:/usr", run)
        self.assertIn(f"{rootfs}/device:/device", run)
        self.assertNotIn(f"{rootfs}/run:/run", run)
        self.assertIn("/source:/workspace", run)
        self.assertIn("/other:/other", run)
        self.assertEqual(run[run.index("--network") + 1], "host")
        self.assertEqual(run[run.index("--label") + 1], "test=yes")
        self.log.unlink()
        cleaned = self.run_function("clean_project", "y\n")
        self.assertEqual(cleaned.returncode, 0, cleaned.stdout + cleaned.stderr)
        cleanup = next(args for args in self.commands() if args[:2] == ["docker", "run"])
        self.assertIn(f"{rootfs}:/mnt/rootfs", cleanup)


if __name__ == "__main__":
    unittest.main()
