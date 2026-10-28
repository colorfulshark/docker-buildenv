# docker-buildenv
## What is it

This tool can start a OS-Level container, just like LXC/LXD does!

So why not LXC/LXD? If you can use LXC/LXD, just play with it! If you can't, please keep reading.

Docker is normally a APP-Level container, it's OK for **deployment**, but not for **development**, Why?

1. Lack of init process
In a development environment, we need a real init process, such as systemd, rather that a fake one, like bash.

2. Hard to keep changes
Docker use overlayfs for rootfs, which will grow up all the time, and once you delete the container, you lose everything.


How does buildenv solve those problems:
1. Start real init process
While running the container, buildenv will launch the init program, such as systemd.

2. Mount everything outside the container
We use an empty Docker image as the base system and bind-mount the persistent rootfs entries into the container. `/tmp` uses tmpfs by default.

Finally, you will get a nearly real OS container, you can install every program or service in it, even a desktop is possible!

Try it by yourself!


## How to use

You need to install docker engine first, and you need to have permission to operate with docker!
Please refer to https://docs.docker.com/engine/install

1. Install buildenv

```
./install.sh
```

The installer runs as your current user; do not use sudo. It installs the command
to `~/.local/bin` and project configurations and templates to
`${XDG_CONFIG_HOME:-$HOME/.config}/buildenv`. Existing configuration files are
preserved when you reinstall.

Make sure `~/.local/bin` is on your `PATH`. If needed, add this line to your shell
startup file (for example, `~/.bashrc`) and reload it:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

When upgrading from a system-wide installation, copy any projects and templates
you want to keep from `/etc/buildenv` into the corresponding user configuration
directories. Run `buildenv` as your regular user with Docker access.

2. Create a project interactively

```sh
buildenv create my-project
```

You can also run `buildenv create` and enter the name when prompted. New project
names contain 1–63 lowercase letters, digits or hyphens, starting and ending with
a letter or digit. Existing project configurations are never overwritten.

The wizard selects an installed template by distribution, release and variant.
Enter a menu number or the full name; single choices are selected automatically.
Only container templates compatible with the host architecture are offered.
The historical `debian-11` and `ubuntu-12` templates are excluded from creation.
Custom templates without a type or architecture restriction remain selectable.

Choose an empty rootfs directory, or accept the default
`${XDG_DATA_HOME:-$HOME/.local/share}/buildenv/rootfs/my-project`. Missing directories
are created. Absolute paths, relative paths, `~/` and spaces are supported; colons
and newlines are rejected. Paths are saved as absolute paths, and input is never
evaluated as shell code. Creation uses no network or Docker commands. Press Ctrl-C
or send EOF to cancel.

3. Init your project
```
buildenv init my-project
```

Initialization resets the downloaded image's network configuration when its init
is systemd. Docker supplies the container's addresses, routes and DNS; networkd
and NetworkManager are configured to leave interfaces unmanaged. Existing
networkd, NetworkManager, Netplan, ifupdown and sysconfig interface configurations
are removed, while loopback configuration and `.link` rules are retained. Where
present, cloud-init network generation and dhcpcd interface management are also
disabled. Network services remain installed and available.

This happens only during `init`, before the rootfs is marked ready. Upgrading
buildenv, `start` and `restart` do not reset an existing rootfs or repair its
network configuration. Non-systemd images keep their network configuration.
For all images, Docker provides `/etc/resolv.conf` when the container is created.

4. Start your project
```
buildenv start my-project
```

Now you are there!

New containers mount `/tmp` as a writable tmpfs with mode `1777` and execution
enabled for build tools. Its contents are discarded when the container stops.
The rootfs `tmp` directory is not mounted or deleted. An explicit `/tmp` mount in
the project's `volume` array takes precedence over the default tmpfs.
For an existing container, run `buildenv restart my-project` to apply this change.

New containers explicitly identify themselves to systemd with `container=docker`
and bind-mount `/sys/power` read-only. Privileged containers otherwise have access
to the host kernel's power controls: the container's logind can react to a closed
laptop lid using its own policy, even when the host's logind ignores it. The
read-only mount blocks writes that would suspend or hibernate the host, while
keeping systemd and logind available. See the
[systemd container interface](https://systemd.io/CONTAINER_INTERFACE/) and the
[kernel sleep interface](https://docs.kernel.org/admin-guide/pm/sleep-states.html#basic-sysfs-interfaces-for-system-suspend-and-hibernation).
The Docker host must provide `/sys/power`. This protection covers ordinary power
management; a privileged process can deliberately undo the mount.

After upgrading, recreate existing containers with `buildenv restart my-project`
before starting them with the laptop lid closed. A plain `start` reuses an existing
container's original mounts and environment. Restart preserves the persistent
rootfs.

You can also just execute buildenv for help.

To edit advanced settings, open the generated configuration:

```sh
vim "${XDG_CONFIG_HOME:-$HOME/.config}/buildenv/projects/my-project"
```

Configurations are Bash files and can also be written manually. For example:

```sh
name="my-project"
template="debian-bookworm"
rootfs_dir="${XDG_DATA_HOME:-$HOME/.local/share}/buildenv/rootfs/my-project"

# Optional volume mount arguments (Bash array)
# volume=(-v "/path/to/source:/workspace:rw")

# Optional port forwarding arguments (Bash array)
# port=(-p "0.0.0.0:8080:80/tcp")

# Optional Docker run arguments
# extra_option="--label project=my-project"
```

When writing a configuration manually, create its empty rootfs directory before
running `init`. `extra_option` retains its whitespace-separated argument syntax;
shell quoting inside that string is not interpreted.

## Manage project mounts

```sh
buildenv mount my-project
```

Run `buildenv mount` without a project name to select an existing project. The
wizard shows current mounts and offers **add**, **edit**, **delete**, **save** and
**quit**, selected by name or menu number. Changes are kept in memory until you
save; quit, EOF or Ctrl-C discards unsaved changes. No network or Docker commands
are run. Project templates do not need to be installed to manage mounts.

For each bind mount, choose an existing host directory or regular file, an
absolute container target, and `rw` (default) or `ro`. During editing, Enter keeps
the current field; other existing mount options are retained. Host paths support
relative paths, `~/`, spaces and literal shell characters, and are saved as
absolute paths. Sources are never created automatically. Colons and newlines are
not accepted in paths. Container targets are normalized without consulting host
symlinks, must not be `/`, and must be unique within the project. A user mount
replaces an automatic rootfs mount with the same target.

`volume` must be a Bash indexed array, or be omitted for no custom mounts:

```sh
volume=(
    -v "/home/user/source:/workspace:rw"
    --volume "/home/user/input file:/data/input:ro"
    --volume=/home/user/cache:/cache:rw
)
```

String configurations such as `volume="-v /source:/workspace"` are not supported;
convert them manually to arrays. Unsupported array arguments are rejected. Named
volumes already present in an array can be kept or deleted, but the wizard only
adds or edits bind mounts.

Saving maintains one `# BEGIN buildenv managed volume` / `# END buildenv managed
volume` block at the end of the project configuration. It overrides earlier
`volume` assignments and preserves other configuration content. Use the wizard
or edit that block to change managed mounts. Saves preserve file permissions and
symlinks, and refuse conflicting edits from another session.

New containers use the saved mounts on `start`. To apply changes to an existing
container, recreate it with:

```sh
buildenv restart my-project
```

## Manage project port forwarding

```sh
buildenv port my-project
```

Run `buildenv port` without a project name to select one. Like the mount wizard,
it offers **add**, **edit**, **delete**, **save** and **quit** by name or menu
number. Unsaved changes are discarded on quit, EOF or Ctrl-C. No Docker or network
commands are run, and templates do not need to be installed.

Each mapping specifies a host IPv4 address (default `0.0.0.0`, all IPv4
addresses), a required host port, a required container port, and `tcp` (default)
or `udp`. Enter keeps the existing field during editing. Ports must be single
decimal integers from 1 to 65535; IPv6, ranges and automatically assigned host
ports are not supported. Addresses and port numbers are normalized when saved.
Use `127.0.0.1` to bind specifically to the host loopback address.

For the same protocol and host port, identical addresses conflict, and `0.0.0.0`
conflicts with every specific address. Different specific addresses can share a
port, as can TCP and UDP. Only conflicts within this project configuration are
checked. Host port availability and actual binding are handled by Docker at
container creation; the wizard does not inspect sockets or modify firewall rules.

The `port` setting is a Bash indexed array, or can be omitted for no mappings:

```sh
port=(
    -p "0.0.0.0:8080:80/tcp"
    --publish "127.0.0.1:5353:53/udp"
    --publish=127.0.0.1:8443:443
)
```

The accepted specification is `[IPv4:]HOST_PORT:CONTAINER_PORT[/tcp|udp]`.
Omitted addresses and protocols default to `0.0.0.0` and `tcp`. The wizard saves
complete `-p IP:HOST:CONTAINER/PROTOCOL` pairs with safe Bash escaping in one
`# BEGIN buildenv managed port` / `# END buildenv managed port` block. String and
associative-array settings are rejected; there is no automatic migration.

With nonempty port mappings, saving and startup reject host network mode
(`--network host`, `--net host` and their `=host` forms) and additional
`-p`/`--publish`/`-P`/`--publish-all` flags in `extra_option`. Adjust those options
manually; the wizard does not remove them. Host networking ignores published
ports, as described in the [Docker documentation](https://docs.docker.com/engine/network/drivers/host/).
An empty `port` array leaves existing networking and extra options unchanged.

Mount and port editors share a configuration lock, preserve each other's managed
blocks, and retain the same atomic save, permission, symlink and conflict checks.
Saving an unchanged list does not rewrite the file. Changes apply on new container
creation; use `buildenv restart my-project` to apply them to an existing container.

## Image templates

The templates cover all 99 distribution/release/variant combinations in the
[Linux Containers system image index](https://images.linuxcontainers.org/meta/1.0/index-system)
retrieved on 2026-10-26. Architectures share a template; the downloader selects
the matching host architecture. Supported host mappings are `x86_64` → `amd64`,
`aarch64`/`arm64` → `arm64`, `armv7l`/`armv8l` → `armhf`,
`loongarch64` → `loong64`, and `riscv64` → `riscv64`. Availability varies by image;
each generated template records its indexed architectures in `DISTRO_ARCHES`.

List the installed templates with `buildenv template`. Names use
`<distribution>-<release>` for the `default` variant and
`<distribution>-<release>-<variant>` for other variants. Examples:

```sh
template="debian-bookworm"
template="ubuntu-noble-cloud"
template="alpine-3.24-tinycloud"
template="gentoo-current-openrc"
template="gentoo-current-systemd"
template="voidlinux-current-musl"
```

`DISTRO_CODE` stores the exact release identifier from the index, including
codenames and rolling release names. `DISTRO_VARIANT` selects the variant instead
of always downloading `default`. Minimal Alpine, BusyBox and OpenWrt images use
`/bin/sh` for the interactive shell.

Initialization and cleanup use the official Docker Hub `alpine:latest` image as
the bootstrap helper. A locally cached image is reused; it is pulled only when
missing. To update the cached image manually, run `docker pull alpine:latest`.
No Debian rootfs is downloaded or imported for bootstrap. An old
`buildenv_bootstrap` image can be removed manually if no longer needed; it is
neither reused nor automatically deleted. Docker selects the platform; pull
failures, including unsupported platforms, stop the operation without a fallback.

NixOS images use `rootfs.squashfs`. Their initialization runs
`apk add --no-cache squashfs-tools` inside the temporary Alpine helper container,
which requires network access to Alpine package repositories. Ordinary tar
rootfs images use Alpine's bundled extraction tools without installing packages.
NetBSD is included in the catalogue as a
`virtual-machine` template; it provides only `disk.qcow2` and cannot run under
Docker, so initialization and startup report that limitation before creating
Docker images. Catalogue coverage does not imply every image has been boot-tested
with this tool.

The historical `debian-11` and `ubuntu-12` templates are no longer bundled.
Existing user copies can still serve already initialized projects, but their
releases are absent from the current index and cannot currently be downloaded.
The bundled example configuration uses `debian-bookworm`.

To refresh the repository templates using Python 3, then install missing templates
into your user configuration directory:

```sh
python3 scripts/update-templates.py
./install.sh
```

For a saved index, use `python3 scripts/update-templates.py --index /path/to/index-system`.
The generator overwrites templates represented by that index and preserves other
files, including historical and custom templates. The installer preserves existing
user configuration, so existing installed templates must be updated manually when
you want to replace them.

Run the offline checks with `python3 -m unittest discover -s tests`.
