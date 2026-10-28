import os
from pathlib import Path
import select
import shlex
import shutil
import signal
import stat
import subprocess
import time
import unittest

from test_create import ProjectFixture, ROOT


BEGIN = "# BEGIN buildenv managed volume"
END = "# END buildenv managed volume"


class MountFixture(ProjectFixture):
    def setUp(self):
        super().setUp()
        result = self.create()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.project_file = self.projects / "demo"
        self.source = self.base / "source with spaces"
        self.source.mkdir()
        self.input_file = self.base / "input file"
        self.input_file.touch()

    def mount(self, input="save\n", name="demo"):
        return self.run_cli(["mount"] + ([name] if name is not None else []), input)

    def append_config(self, text):
        with self.project_file.open("a") as config:
            config.write("\n" + text + "\n")

    def set_mounts(self, *specs, flag="-v"):
        words = " ".join(f"{flag} {shlex.quote(spec)}" for spec in specs)
        self.append_config(f"volume=({words})")

    def volume(self):
        output = subprocess.check_output([
            "bash", "-c", 'source "$1"; if [ "${#volume[@]}" -gt 0 ]; then printf "%s\\0" "${volume[@]}"; fi',
            "bash", str(self.project_file),
        ], env=self.env, cwd=self.base)
        return [value.decode() for value in output.split(b"\0")[:-1]]

    def assert_clean(self, directory=None):
        self.assertEqual(list((directory or self.projects).glob(".mount*")), [])
        self.assertEqual(list((directory or self.projects).glob(".buildenv*")), [])

    def start_mount(self, input=""):
        process = subprocess.Popen([str(ROOT / "buildenv"), "mount", "demo"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   cwd=self.base, env=self.env, start_new_session=True)
        self.addCleanup(self.stop_process, process)
        if input:
            process.stdin.write(input.encode())
            process.stdin.flush()
        return process

    def wait_for_prompt(self, process, phrase):
        output = b""
        deadline = time.monotonic() + 5
        while phrase not in output and time.monotonic() < deadline:
            if select.select([process.stderr], [], [], 0.1)[0]:
                data = os.read(process.stderr.fileno(), 4096)
                if not data:
                    break
                output += data
        self.assertIn(phrase, output)

class MountTests(MountFixture, unittest.TestCase):
    def test_add_directory_and_file_mounts_offline(self):
        result = self.mount(f"add\n{self.source}\n/work/../workspace/\n\nadd\n{self.input_file}\n/input\nro\nsave\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.volume(), ["-v", f"{self.source}:/workspace:rw", "-v", f"{self.input_file}:/input:ro"])
        self.assertIn("buildenv restart demo", result.stdout)
        self.assertEqual(self.commands(), [])
        self.assert_clean()

    def test_project_selection_by_name_number_and_single_choice(self):
        self.assertEqual(self.mount(name=None).returncode, 0)
        self.assertEqual(self.create(name="other").returncode, 0)
        for choice in ["demo", "1"]:
            with self.subTest(choice=choice):
                result = self.mount(f"invalid\n{choice}\nquit\n", name=None)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Invalid selection", result.stderr)
        self.assert_clean()

    def test_invalid_or_missing_project_and_extra_arguments(self):
        for name in ["", ".", "..", "../demo", "a/demo", "missing"]:
            self.assertNotEqual(self.mount(name=name).returncode, 0)
        result = self.run_cli(["mount", "demo", "extra"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Usage: buildenv mount [PROJECT]", result.stderr)
        shutil.rmtree(self.projects)
        result = self.mount(name=None)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No projects found", result.stderr)

    def test_templates_are_not_needed(self):
        shutil.rmtree(self.templates)
        result = self.mount(f"add\n{self.source}\n/work\nro\nsave\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commands(), [])

    def test_edit_keeps_defaults_and_non_mode_options(self):
        self.set_mounts(f"{self.source}:/original:ro,z,rshared")
        result = self.mount("edit\n\n/new/../target\ninvalid\nrw\nsave\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Access mode must be", result.stderr)
        self.assertEqual(self.volume(), ["-v", f"{self.source}:/target:rw,z,rshared"])
        result = self.mount("edit\n\n\n\nsave\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.volume(), ["-v", f"{self.source}:/target:rw,z,rshared"])

    def test_delete_and_reindex_then_edit(self):
        self.set_mounts(f"{self.source}:/one:rw", f"{self.input_file}:/two:ro")
        result = self.mount("delete\n1\nedit\n\n/changed\n\nsave\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.volume(), ["-v", f"{self.input_file}:/changed:ro"])
        self.assertEqual(self.mount("delete\nsave\n").returncode, 0)
        self.assertEqual(self.volume(), [])
        self.assert_clean()

    def test_empty_edit_delete_and_invalid_action_retry(self):
        result = self.mount("invalid\nedit\ndelete\nquit\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No mounts to edit", result.stderr)
        self.assertIn("No mounts to delete", result.stderr)
        self.assert_clean()

    def test_duplicate_targets_and_invalid_paths_retry(self):
        self.set_mounts(f"{self.source}:/workspace:rw")
        result = self.mount(f"add\n\n{self.base}/missing\nbad:path\n{self.input_file}\nrelative\n/\n/a/../workspace/\n/new\nro\nsave\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("existing directory or regular file", result.stderr)
        self.assertIn("Duplicate container mount target", result.stderr)
        self.assertEqual(self.volume()[-1], f"{self.input_file}:/new:ro")
        self.assertFalse((self.base / "missing").exists())

    def test_source_resolution_and_literal_special_characters(self):
        source = self.base / 'source $(touch PWNED) `touch PWNED` $HOME %s "quote" \\path'
        source.mkdir()
        destination = '/literal $(touch PWNED) $HOME "quote" \\path'
        result = self.mount(f"add\n./{source.name}\n{destination}\nro\nadd\n~/input file\n/bin\n\nsave\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.volume(), ["-v", f"{source}:{destination}:ro", "-v", f"{self.input_file}:/bin:rw"])
        self.assertFalse((self.base / "PWNED").exists())

    def test_source_symlink_with_reserved_characters_in_resolved_path_is_rejected(self):
        for i, name in enumerate(["bad:source", "bad\n"]):
            with self.subTest(name=name):
                bad = self.base / name
                bad.mkdir()
                alias = self.base / f"alias{i}"
                alias.symlink_to(bad)
                result = self.mount(f"add\n{alias}\n{self.source}\n/good{i}\n\nsave\n")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Resolved source path", result.stderr)
                self.assertEqual(self.volume()[-1], f"{self.source}:/good{i}:rw")

    def test_existing_named_volumes_are_kept_but_not_edited(self):
        self.set_mounts("cache:/cache:rw", flag="--volume")
        result = self.mount(f"edit\nadd\n{self.source}\n/work\n\nsave\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("only bind mounts can be edited", result.stderr)
        self.assertEqual(self.volume()[:2], ["-v", "cache:/cache:rw"])
        result = self.mount("delete\n1\nsave\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.volume(), ["-v", f"{self.source}:/work:rw"])

    def test_array_forms_and_declared_local_arrays(self):
        for declaration in [
            f'volume=(--volume={shlex.quote(str(self.source) + ":/work:rw")})',
            f'declare -a volume=(--volume {shlex.quote(str(self.source) + ":/work:rw")})',
        ]:
            with self.subTest(declaration=declaration):
                self.append_config(declaration)
                result = self.mount("edit\n\n\nro\nsave\n")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.volume(), ["-v", f"{self.source}:/work:ro"])
                # Restore the original project to exercise the next declaration.
                self.project_file.unlink()
                self.assertEqual(self.create().returncode, 0)

    def test_strings_and_associative_arrays_are_rejected_without_writes(self):
        original = self.project_file.read_bytes()
        for declaration in ['volume=""', 'volume="-v /source:/work"', 'declare -A volume=([source]=target)']:
            with self.subTest(declaration=declaration):
                self.project_file.write_bytes(original)
                self.append_config(declaration)
                before = self.project_file.read_bytes()
                result = self.mount()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("volume must be a Bash indexed array", result.stderr)
                self.assertEqual(self.project_file.read_bytes(), before)
                self.assert_clean()

    def test_invalid_array_arguments_and_targets_are_rejected(self):
        original = self.project_file.read_bytes()
        for words in ["--privileged", "-v", "-v missingtarget", "-v /src:relative", "-v /src:/", "-v /src:/work:rw:bad", "-v /src:/one -v /other:/a/../one"]:
            with self.subTest(words=words):
                self.project_file.write_bytes(original)
                self.append_config(f"volume=({words})")
                before = self.project_file.read_bytes()
                self.assertNotEqual(self.mount().returncode, 0)
                self.assertEqual(self.project_file.read_bytes(), before)
                self.assert_clean()

    def test_preserves_other_configuration_permissions_and_single_block(self):
        self.append_config('# keep comment\nextra_option="--network host"\ncustom="literal $HOME"')
        original = self.project_file.read_bytes()
        self.project_file.chmod(0o640)
        self.assertEqual(self.mount(f"add\n{self.source}\n/work\n\nsave\n").returncode, 0)
        self.assertTrue(self.project_file.read_bytes().startswith(original))
        self.assertEqual(self.mount("edit\n\n/other\n\nsave\n").returncode, 0)
        content = self.project_file.read_text()
        self.assertEqual(content.count(BEGIN), 1)
        self.assertEqual(content.count(END), 1)
        self.assertTrue(content.startswith(original.decode()))
        self.assertEqual(stat.S_IMODE(self.project_file.stat().st_mode), 0o640)
        self.assert_clean()

    def test_invalid_markers_are_not_changed(self):
        original = self.project_file.read_bytes()
        for markers in [BEGIN, END, BEGIN + "\n" + BEGIN + "\n" + END, BEGIN + "\n" + END + "\n" + BEGIN + "\n" + END]:
            with self.subTest(markers=markers):
                self.project_file.write_bytes(original)
                self.append_config(markers)
                before = self.project_file.read_bytes()
                result = self.mount()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("markers are incomplete or ambiguous", result.stderr)
                self.assertEqual(self.project_file.read_bytes(), before)
                self.assert_clean()

    def test_symlink_configuration_updates_target_without_replacing_link(self):
        actual = self.base / "external config"
        self.project_file.rename(actual)
        self.project_file.symlink_to(actual)
        result = self.mount(f"add\n{self.source}\n/work\n\nsave\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.project_file.is_symlink())
        self.assertIn(BEGIN, actual.read_text())
        self.assertEqual(self.volume(), ["-v", f"{self.source}:/work:rw"])
        self.assert_clean(self.base)

    def test_quit_eof_and_unchanged_save_do_not_modify_configuration(self):
        original = self.project_file.read_bytes()
        original_mtime = self.project_file.stat().st_mtime_ns
        for input in ["quit\n", "save\n", "", "add\n", f"add\n{self.source}\n", f"add\n{self.source}\n/work\n\nquit\n"]:
            with self.subTest(input=input):
                self.mount(input)
                self.assertEqual(self.project_file.read_bytes(), original)
                self.assertEqual(self.project_file.stat().st_mtime_ns, original_mtime)
                self.assert_clean()

    def test_sigint_discards_staged_changes_and_cleans_lock(self):
        original = self.project_file.read_bytes()
        process = self.start_mount(f"add\n{self.source}\n/work\n\n")
        self.wait_for_prompt(process, b"-> /work")
        os.killpg(process.pid, signal.SIGINT)
        _, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 130, stderr.decode())
        self.assertEqual(self.project_file.read_bytes(), original)
        self.assert_clean()

    def test_write_failures_preserve_configuration(self):
        original = self.project_file.read_bytes()
        for command in ["chmod", "mv"]:
            with self.subTest(command=command):
                self.stub(command, "import sys\nsys.exit(1)\n")
                result = self.mount(f"add\n{self.source}\n/work\n\nsave\n")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.project_file.read_bytes(), original)
                self.assert_clean()
                (self.bin / command).unlink()

    def test_concurrent_session_is_refused_and_external_edit_is_preserved(self):
        process = self.start_mount()
        self.wait_for_prompt(process, b"Select action")
        second = self.mount()
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("locked", second.stderr)
        self.append_config("# external edit")
        changed = self.project_file.read_bytes()
        _, stderr = process.communicate(f"add\n{self.source}\n/work\n\nsave\n".encode(), timeout=10)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn(b"changed during editing", stderr)
        self.assertEqual(self.project_file.read_bytes(), changed)
        self.assert_clean()

    def test_mount_array_reaches_docker_and_overrides_rootfs(self):
        self.assertEqual(self.mount(f"add\n{self.source}\n/usr\nro\nsave\n").returncode, 0)
        rootfs = self.rootfs()
        (rootfs / ".buildenv").touch()
        (rootfs / "usr").mkdir()
        (rootfs / "etc").mkdir()
        self.env["TEST_NEW_CONTAINER"] = "1"
        result = self.run_function("start_project")
        self.assertEqual(result.returncode, 0, result.stderr)
        run = next(row for row in self.commands() if row[:2] == ["docker", "run"])
        self.assertIn(f"{self.source}:/usr:ro", run)
        self.assertNotIn(f"{rootfs}/usr:/usr", run)
        self.assertIn(f"{rootfs}/etc:/etc", run)

    def test_tmpfs_is_used_with_or_without_rootfs_tmp(self):
        rootfs = self.rootfs()
        (rootfs / ".buildenv").touch()
        self.env["TEST_NEW_CONTAINER"] = "1"
        for existing_tmp in [False, True]:
            with self.subTest(existing_tmp=existing_tmp):
                if existing_tmp:
                    (rootfs / "tmp").mkdir()
                    (rootfs / "tmp/keep").write_text("existing temporary data")
                result = self.run_function("start_project")
                self.assertEqual(result.returncode, 0, result.stderr)
                run = next(row for row in self.commands() if row[:2] == ["docker", "run"])
                tmpfs = [run[i + 1] for i, arg in enumerate(run) if arg == "--tmpfs"]
                self.assertCountEqual(tmpfs, [
                    "/tmp:rw,exec,nosuid,nodev,mode=1777",
                    "/dev/shm:rw,nosuid,nodev,noexec,mode=1777",
                ])
                self.assertNotIn(f"{rootfs}/tmp:/tmp", run)
                if existing_tmp:
                    self.assertEqual((rootfs / "tmp/keep").read_text(), "existing temporary data")
                self.log.unlink()

    def test_explicit_tmp_mount_overrides_default_tmpfs(self):
        rootfs = self.rootfs()
        (rootfs / ".buildenv").touch()
        (rootfs / "tmp").mkdir()
        self.env["TEST_NEW_CONTAINER"] = "1"
        for source in [str(self.source), "tmp-cache"]:
            with self.subTest(source=source):
                self.set_mounts(f"{source}:/tmp:rw")
                result = self.run_function("start_project")
                self.assertEqual(result.returncode, 0, result.stderr)
                run = next(row for row in self.commands() if row[:2] == ["docker", "run"])
                self.assertIn(f"{source}:/tmp:rw", run)
                tmpfs = [run[i + 1] for i, arg in enumerate(run) if arg == "--tmpfs"]
                self.assertEqual(tmpfs, ["/dev/shm:rw,nosuid,nodev,noexec,mode=1777"])
                self.assertNotIn(f"{rootfs}/tmp:/tmp", run)
                self.log.unlink()

    def test_tmp_subdirectory_mount_keeps_default_tmpfs(self):
        self.set_mounts(f"{self.source}:/tmp/cache:rw")
        (self.rootfs() / ".buildenv").touch()
        self.env["TEST_NEW_CONTAINER"] = "1"
        result = self.run_function("start_project")
        self.assertEqual(result.returncode, 0, result.stderr)
        run = next(row for row in self.commands() if row[:2] == ["docker", "run"])
        self.assertIn("--tmpfs", run)
        self.assertIn(f"{self.source}:/tmp/cache:rw", run)

    def test_loading_multiple_projects_does_not_leak_mounts(self):
        self.set_mounts(f"{self.source}:/work:rw")
        self.assertEqual(self.create(name="other").returncode, 0)
        result = subprocess.run([
            "bash", "-c", 'source "$1" help >/dev/null; load_project_metadata demo; '
            '[ "${#volume[@]}" -eq 2 ] || exit 1; load_project_metadata other; '
            '[ "${#volume[@]}" -eq 0 ]', "bash", str(ROOT / "buildenv"),
        ], cwd=self.base, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
