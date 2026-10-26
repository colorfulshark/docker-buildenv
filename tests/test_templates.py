import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("update_templates", ROOT / "scripts/update-templates.py")
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def index_row(distro, release, arch="amd64", variant="default"):
    return f"{distro};{release};{arch};{variant};20261026_00:00;/images/{distro}/{release}/{arch}/{variant}/20261026_00:00/\n"


INDEX = "".join([
    *(index_row("debian", "bookworm", arch) for arch in
      ["amd64", "arm64", "armhf", "loong64", "riscv64"]),
    index_row("debian", "bookworm", variant="cloud"),
    index_row("debian", "trixie"),
    index_row("alpine", "edge", variant="tinycloud"),
    index_row("gentoo", "current", variant="openrc"),
    index_row("gentoo", "current", variant="systemd"),
    index_row("voidlinux", "current", variant="musl"),
    index_row("nixos", "unstable"),
    index_row("netbsd", "11.0"),
])


class TemplateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="buildenv-tests-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.config = self.base / "config with spaces/buildenv"
        self.templates = self.config / "templates"
        generator.generate(INDEX, self.templates)
        self.index = self.base / "index-system"
        self.index.write_text(INDEX)
        self.log = self.base / "commands.jsonl"
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.env = os.environ.copy()
        self.env.update(
            HOME=str(self.base), XDG_CONFIG_HOME=str(self.config.parent),
            PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
            TEST_ARCH="x86_64", TEST_INDEX=str(self.index), TEST_LOG=str(self.log),
        )
        self.stub("uname", 'import os\nprint(os.environ["TEST_ARCH"])\n')
        self.stub("column", 'import sys\nsys.stdout.write(sys.stdin.read())\n')
        self.stub("wget", '''import json, lzma, os, sys
from pathlib import Path
args = sys.argv[1:]
url = args[-1]
with open(os.environ["TEST_LOG"], "a") as log:
    log.write(json.dumps(["wget", url]) + "\\n")
output = Path(args[args.index("-O") + 1])
if url.endswith("/index-system"):
    output.write_bytes(Path(os.environ["TEST_INDEX"]).read_bytes())
elif url.endswith(".tar.xz"):
    output.write_bytes(lzma.compress(b"test rootfs"))
else:
    output.write_bytes(b"test squashfs")
''')
        self.stub("docker", '''import json, os, sys
args = sys.argv[1:]
with open(os.environ["TEST_LOG"], "a") as log:
    log.write(json.dumps(["docker"] + args) + "\\n")
if args[:2] == ["image", "inspect"] and os.environ.get("TEST_MISSING_IMAGE"):
    sys.exit(1)
if args and args[0] == "ps":
    print("test-container")
''')

    def stub(self, name, body):
        script = self.bin / name
        script.write_text(f"#!{sys.executable}\n{body}")
        script.chmod(0o755)

    def run_function(self, *args):
        work = self.base / "work"
        work.mkdir(exist_ok=True)
        for archive in work.glob("rootfs*"):
            archive.unlink()
        return subprocess.run([
            "bash", "-c",
            'source "$1" help >/dev/null; tmp_dir="$2"; '
            'server=https://images.linuxcontainers.org; shift 2; "$@"',
            "bash", str(ROOT / "buildenv"), str(work), *args,
        ], env=self.env, capture_output=True, text=True)

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def project(self, template):
        projects = self.config / "projects"
        projects.mkdir(exist_ok=True)
        rootfs = self.base / "rootfs"
        rootfs.mkdir(exist_ok=True)
        (projects / "project").write_text(f'template="{template}"\nname=project\nrootfs_dir="{rootfs}"\n')
        return rootfs

    def test_generator_groups_architectures_and_preserves_other_files(self):
        legacy = self.templates / "legacy"
        legacy.write_text("custom config")
        before = {path.name: path.read_bytes() for path in self.templates.iterdir()}
        self.assertEqual(generator.generate(INDEX, self.templates), 9)
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.templates.iterdir()})
        self.assertIn('DISTRO_ARCHES="amd64 arm64 armhf loong64 riscv64"',
                      (self.templates / "debian-bookworm").read_text())

    def test_invalid_index_does_not_write_templates(self):
        for index in ["", "invalid", INDEX + index_row("../invalid", "release")]:
            output = self.base / "invalid"
            with self.assertRaises(ValueError):
                generator.generate(index, output)
            self.assertFalse(output.exists())

    def test_template_listing_includes_variants_and_vm_type(self):
        result = self.run_function("show_templates")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("gentoo-current-systemd:gentoo:current:current:systemd:container", result.stdout)
        self.assertIn("netbsd-11.0:netbsd:11.0:11.0:default:virtual-machine", result.stdout)

    def test_download_selects_each_variant(self):
        for distro, release, variant in [
            ("debian", "bookworm", "default"), ("debian", "bookworm", "cloud"),
            ("alpine", "edge", "tinycloud"), ("gentoo", "current", "openrc"),
            ("gentoo", "current", "systemd"), ("voidlinux", "current", "musl"),
        ]:
            with self.subTest(variant=variant):
                result = self.run_function("download_image", distro, release, variant)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"/{distro}/{release}/amd64/{variant}/", self.commands()[-1][-1])
                self.assertEqual((self.base / "work/rootfs.tar").read_bytes(), b"test rootfs")

    def test_architecture_mappings(self):
        for host, image in [("x86_64", "amd64"), ("aarch64", "arm64"),
                            ("arm64", "arm64"), ("armv7l", "armhf"),
                            ("armv8l", "armhf"), ("loongarch64", "loong64"),
                            ("riscv64", "riscv64")]:
            with self.subTest(host=host):
                self.env["TEST_ARCH"] = host
                result = self.run_function("download_image", "debian", "bookworm")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"/{image}/default/", self.commands()[-1][-1])

    def test_missing_image_does_not_request_rootfs(self):
        result = self.run_function("download_image", "debian", "bullseye")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no image found for debian/bullseye/amd64/default", result.stdout)
        self.assertEqual(len(self.commands()), 1)

    def test_unsupported_architecture_fails_before_downloading(self):
        self.env["TEST_ARCH"] = "mips64"
        result = self.run_function("download_image", "debian", "bookworm")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported host architecture", result.stdout)
        self.assertEqual(self.commands(), [])

    def test_vm_template_fails_before_docker_or_download(self):
        self.project("netbsd-11.0")
        for command in ["init_project", "start_project", "clean_project"]:
            with self.subTest(command=command):
                result = self.run_function(command, "project")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("cannot run in Docker", result.stdout)
                self.assertEqual(self.commands(), [])

    def test_squashfs_initialization_and_current_bootstrap(self):
        self.project("nixos-unstable")
        self.env["TEST_MISSING_IMAGE"] = "1"
        result = self.run_function("init_project", "project")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        urls = [args[-1] for args in self.commands() if args[0] == "wget"]
        self.assertTrue(any("/debian/trixie/amd64/default/" in url for url in urls))
        self.assertTrue(urls[-1].endswith("rootfs.squashfs"))
        extraction = next(args[-1] for args in self.commands() if args[:2] == ["docker", "run"])
        self.assertIn("apt-get install -y squashfs-tools && unsquashfs", extraction)
        self.assertIn("&& touch /mnt/rootfs/.buildenv", extraction)

    def test_minimal_image_uses_sh(self):
        rootfs = self.project("alpine-edge-tinycloud")
        (rootfs / ".buildenv").touch()
        result = self.run_function("start_project", "project")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.commands()[-1][-1], "/bin/sh")


if __name__ == "__main__":
    unittest.main()
