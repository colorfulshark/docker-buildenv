import os
import shlex
import shutil
import signal
import stat
import subprocess
import unittest

from test_mount import MountFixture, ROOT


BEGIN = "# BEGIN buildenv managed port"
END = "# END buildenv managed port"


class PortTests(MountFixture, unittest.TestCase):
    def port_editor(self, input="save\n", name="demo"):
        return self.run_cli(["port"] + ([name] if name is not None else []), input)

    def set_ports(self, *specs, flag="-p"):
        words = " ".join(f"{flag} {shlex.quote(spec)}" for spec in specs)
        self.append_config(f"port=({words})")

    def ports(self):
        output = subprocess.check_output([
            "bash", "-c", 'source "$1"; if [ "${#port[@]}" -gt 0 ]; then printf "%s\\0" "${port[@]}"; fi',
            "bash", str(self.project_file),
        ], env=self.env, cwd=self.base)
        return [value.decode() for value in output.split(b"\0")[:-1]]

    def start_port_editor(self, input=""):
        process = subprocess.Popen([str(ROOT / "buildenv"), "port", "demo"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   cwd=self.base, env=self.env, start_new_session=True)
        self.addCleanup(self.stop_process, process)
        if input:
            process.stdin.write(input.encode())
            process.stdin.flush()
        return process

    def test_add_default_tcp_and_explicit_udp_offline(self):
        result = self.port_editor("add\n\n8080\n80\n\nadd\n127.0.0.1\n5353\n53\nudp\nsave\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ports(), ["-p", "0.0.0.0:8080:80/tcp", "-p", "127.0.0.1:5353:53/udp"])
        self.assertIn("buildenv restart demo", result.stdout)
        self.assertEqual(self.commands(), [])
        self.assert_clean()

    def test_selection_and_invalid_project_arguments(self):
        self.assertEqual(self.port_editor(name=None).returncode, 0)
        self.assertEqual(self.create(name="other").returncode, 0)
        for choice in ["demo", "1"]:
            result = self.port_editor(f"invalid\n{choice}\nquit\n", name=None)
            self.assertEqual(result.returncode, 0, result.stderr)
        for name in ["", ".", "..", "../demo", "missing"]:
            self.assertNotEqual(self.port_editor(name=name).returncode, 0)
        result = self.run_cli(["port", "demo", "extra"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Usage: buildenv port [PROJECT]", result.stderr)
        shutil.rmtree(self.projects)
        self.assertIn("No projects found", self.port_editor(name=None).stderr)

    def test_edit_defaults_delete_and_reindex(self):
        self.set_ports("8080:80", "127.0.0.1:8081:81/udp")
        result = self.port_editor("edit\n2\n\n\n82\n\ndelete\n1\nedit\n\n8082\n\n\nsave\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ports(), ["-p", "127.0.0.1:8082:82/udp"])
        self.assertEqual(self.port_editor("delete\nsave\n").returncode, 0)
        self.assertEqual(self.ports(), [])

    def test_invalid_actions_and_empty_edit_delete_retry(self):
        result = self.port_editor("invalid\nedit\ndelete\nquit\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No port mappings to edit", result.stderr)
        self.assertIn("No port mappings to delete", result.stderr)

    def test_ipv4_port_boundaries_and_normalization(self):
        result = self.port_editor("add\n256.0.0.1\n::1\nlocalhost\n127.000.000.001\n\n0\n65536\n8000-8001\n1+1\n00001\n0\n-1\n65535\nsctp\nudp\nsave\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ports(), ["-p", "127.0.0.1:1:65535/udp"])
        self.assertIn("Protocol must be tcp or udp", result.stderr)

    def test_array_forms_and_omitted_address_protocol(self):
        original = self.project_file.read_bytes()
        for declaration in [
            "port=(-p 8080:80)", "port=(--publish 127.0.0.1:8080:80)",
            "port=(--publish=8080:80/udp)", "declare -a port=(-p 8080:80)",
        ]:
            with self.subTest(declaration=declaration):
                self.project_file.write_bytes(original)
                self.append_config(declaration)
                result = self.port_editor("edit\n\n\n81\n\nsave\n")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(self.ports()[1].endswith(":81/udp") if "/udp" in declaration else self.ports()[1].endswith(":81/tcp"))
                self.assertEqual(self.ports()[0], "-p")

    def test_duplicate_and_wildcard_conflicts_retry(self):
        original = self.project_file.read_bytes()
        for existing, attempted in [("127.0.0.1", "127.0.0.1"), ("0.0.0.0", "127.0.0.1"), ("127.0.0.1", "0.0.0.0")]:
            with self.subTest(existing=existing, attempted=attempted):
                self.project_file.write_bytes(original)
                self.set_ports(f"{existing}:8080:80/tcp")
                result = self.port_editor(f"add\n{attempted}\n8080\n81\n\n127.0.0.1\n8081\n81\n\nsave\n")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Conflicting host port mapping", result.stderr)
                self.assertEqual(self.ports()[-1], "127.0.0.1:8081:81/tcp")

    def test_distinct_addresses_and_tcp_udp_can_reuse_host_port(self):
        self.set_ports("127.0.0.1:8080:80/tcp", "127.0.0.2:8080:80/tcp")
        result = self.port_editor("add\n\n8080\n80\nudp\nsave\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ports()[-1], "0.0.0.0:8080:80/udp")
        self.assertEqual(len(self.ports()), 6)

    def test_invalid_array_types_or_specs_never_write_or_call_docker(self):
        original = self.project_file.read_bytes()
        declarations = ['port=""', 'port="-p 8080:80"', 'declare -A port=([host]=container)',
                        'port=(--privileged)', 'port=(-p)', 'port=(-p 80)',
                        'port=(-p 0:80)', 'port=(-p 65536:80)', 'port=(-p 80:0)',
                        'port=(-p 8080-8081:80-81)', 'port=(-p "[::1]:8080:80")',
                        'port=(-p 256.0.0.1:8080:80)', 'port=(-p 8080:80/sctp)',
                        'port=(-p 8080:80/tcp/udp)', 'port=(-p 8080:80 -p 127.0.0.1:8080:81)']
        for declaration in declarations:
            with self.subTest(declaration=declaration):
                self.project_file.write_bytes(original)
                self.append_config(declaration)
                before = self.project_file.read_bytes()
                self.assertNotEqual(self.port_editor().returncode, 0)
                self.assertNotEqual(self.run_function("start_project").returncode, 0)
                self.assertEqual(self.project_file.read_bytes(), before)
                self.assertEqual(self.commands(), [])
                self.assert_clean()

    def test_host_network_and_extra_publish_flags_block_save_and_start(self):
        original = self.project_file.read_bytes()
        for options in ["--network host", "--net host", "--network=host", "--net=host",
                        "-p 9000:90", "-p9000:90", "--publish 9000:90", "--publish=9000:90",
                        "-P", "--publish-all", "--publish-all=true"]:
            with self.subTest(options=options):
                self.project_file.write_bytes(original)
                self.set_ports("8080:80")
                self.append_config(f"extra_option={shlex.quote(options)}")
                before = self.project_file.read_bytes()
                result = self.port_editor()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("extra_option", result.stderr)
                self.assertNotEqual(self.run_function("start_project").returncode, 0)
                self.assertEqual(self.commands(), [])
                self.assertEqual(self.project_file.read_bytes(), before)
                self.assert_clean()

    def test_can_clear_ports_without_changing_host_network_option(self):
        self.set_ports("8080:80")
        self.append_config('extra_option="--network host"')
        result = self.port_editor("save\ndelete\nsave\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ports(), [])
        self.assertIn('extra_option="--network host"', self.project_file.read_text())

    def test_empty_ports_leave_manual_options_usable(self):
        self.append_config('port=()\nextra_option="--network host -p 8080:80"')
        (self.rootfs() / ".buildenv").touch()
        self.env["TEST_NEW_CONTAINER"] = "1"
        result = self.run_function("start_project")
        self.assertEqual(result.returncode, 0, result.stderr)
        run = next(row for row in self.commands() if row[:2] == ["docker", "run"])
        self.assertIn("host", run)
        self.assertIn("8080:80", run)

    def test_mount_and_port_blocks_survive_alternating_edits(self):
        self.assertEqual(self.mount(f"add\n{self.source}\n/work\n\nsave\n").returncode, 0)
        original_volume = self.volume()
        self.assertEqual(self.port_editor("add\n\n8080\n80\n\nsave\n").returncode, 0)
        self.assertEqual(self.mount("edit\n\n/new-work\nro\nsave\n").returncode, 0)
        self.assertEqual(self.port_editor("edit\n\n8081\n\n\nsave\n").returncode, 0)
        content = self.project_file.read_text()
        self.assertEqual(content.count(BEGIN), 1)
        self.assertEqual(content.count("# BEGIN buildenv managed volume"), 1)
        self.assertEqual(self.ports(), ["-p", "0.0.0.0:8081:80/tcp"])
        self.assertNotEqual(self.volume(), original_volume)
        self.assertEqual(self.volume(), ["-v", f"{self.source}:/new-work:ro"])

    def test_preserves_unrelated_content_permissions_and_symlink(self):
        self.append_config('# keep comment\ncustom="literal $HOME"')
        original = self.project_file.read_bytes()
        actual = self.base / "actual configuration"
        self.project_file.rename(actual)
        actual.chmod(0o640)
        self.project_file.symlink_to(actual)
        result = self.port_editor("add\n\n8080\n80\n\nsave\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.project_file.is_symlink())
        self.assertTrue(actual.read_bytes().startswith(original))
        self.assertEqual(stat.S_IMODE(actual.stat().st_mode), 0o640)
        self.assert_clean(self.base)

    def test_ambiguous_port_markers_are_refused(self):
        original = self.project_file.read_bytes()
        for markers in [BEGIN, END, BEGIN + "\n" + BEGIN + "\n" + END,
                        BEGIN + "\n" + END + "\n" + BEGIN + "\n" + END]:
            with self.subTest(markers=markers):
                self.project_file.write_bytes(original)
                self.append_config(markers)
                before = self.project_file.read_bytes()
                result = self.port_editor()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("markers are incomplete or ambiguous", result.stderr)
                self.assertEqual(self.project_file.read_bytes(), before)
                self.assert_clean()

    def test_quit_eof_and_unchanged_save_leave_bytes_and_mtime(self):
        before = self.project_file.read_bytes()
        mtime = self.project_file.stat().st_mtime_ns
        for input in ["save\n", "quit\n", "", "add\n", "add\n\n", "add\n\n8080\n",
                      "add\n\n8080\n80\n\nquit\n"]:
            with self.subTest(input=input):
                self.port_editor(input)
                self.assertEqual(self.project_file.read_bytes(), before)
                self.assertEqual(self.project_file.stat().st_mtime_ns, mtime)
                self.assert_clean()

    def test_sigint_cleans_staged_edit(self):
        original = self.project_file.read_bytes()
        process = self.start_port_editor("add\n\n8080\n80\n\n")
        self.wait_for_prompt(process, b"0.0.0.0:8080 -> 80/tcp")
        os.killpg(process.pid, signal.SIGINT)
        _, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 130, stderr.decode())
        self.assertEqual(self.project_file.read_bytes(), original)
        self.assert_clean()

    def test_write_failure_preserves_original(self):
        original = self.project_file.read_bytes()
        for command in ["chmod", "mv"]:
            with self.subTest(command=command):
                self.stub(command, "import sys\nsys.exit(1)\n")
                result = self.port_editor("add\n\n8080\n80\n\nsave\n")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.project_file.read_bytes(), original)
                self.assert_clean()
                (self.bin / command).unlink()

    def test_mount_and_port_editors_share_lock_in_both_directions(self):
        first = self.start_port_editor()
        self.wait_for_prompt(first, b"Select action")
        for result in [self.mount(), self.port_editor()]:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("locked", result.stderr)
        first.communicate(b"quit\n", timeout=10)
        second = self.start_mount()
        self.wait_for_prompt(second, b"Select action")
        result = self.port_editor()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("locked", result.stderr)
        second.communicate(b"quit\n", timeout=10)
        self.assert_clean()

    def test_external_modification_is_not_overwritten(self):
        process = self.start_port_editor()
        self.wait_for_prompt(process, b"Select action")
        self.append_config("# external change")
        before = self.project_file.read_bytes()
        _, stderr = process.communicate(b"add\n\n8080\n80\n\nsave\n", timeout=10)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn(b"changed during editing", stderr)
        self.assertEqual(self.project_file.read_bytes(), before)
        self.assert_clean()

    def test_port_arguments_reach_docker_with_mounts(self):
        self.assertEqual(self.port_editor("add\n\n8080\n80\n\nadd\n\n5353\n53\nudp\nsave\n").returncode, 0)
        self.set_mounts(f"{self.source}:/work:rw")
        (self.rootfs() / ".buildenv").touch()
        self.env["TEST_NEW_CONTAINER"] = "1"
        result = self.run_function("start_project")
        self.assertEqual(result.returncode, 0, result.stderr)
        run = next(row for row in self.commands() if row[:2] == ["docker", "run"])
        self.assertIn("0.0.0.0:8080:80/tcp", run)
        self.assertIn("0.0.0.0:5353:53/udp", run)
        self.assertEqual(run.count("-p"), 2)
        self.assertIn(f"{self.source}:/work:rw", run)

    def test_port_settings_do_not_leak_between_projects(self):
        self.set_ports("8080:80")
        self.assertEqual(self.create(name="other").returncode, 0)
        result = subprocess.run([
            "bash", "-c", 'source "$1" help >/dev/null; load_project_config demo; '
            '[ "${#port[@]}" -eq 2 ] || exit 1; load_project_config other; '
            '[ "${#port[@]}" -eq 0 ]', "bash", str(ROOT / "buildenv"),
        ], cwd=self.base, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_templates_not_needed(self):
        shutil.rmtree(self.templates)
        result = self.port_editor("add\n\n8080\n80\n\nsave\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commands(), [])


if __name__ == "__main__":
    unittest.main()
