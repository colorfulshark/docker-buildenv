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
We use a empty docker image as the base system, and mount the whole rootfs into the container, so everything will be kept.

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

2. Edit project config
```
vim "${XDG_CONFIG_HOME:-$HOME/.config}/buildenv/projects/project"
```

For example
```
# buildenv template, you can list all templates with 'buildenv template'
template="debian-bookworm"

# the directory to store the rootfs, this directory must exist and be empty
rootfs_dir="${XDG_DATA_HOME:-$HOME/.local/share}/buildenv/rootfs/debian-bookworm"
```

Create the rootfs directory before initializing the project:

```sh
mkdir -p "${XDG_DATA_HOME:-$HOME/.local/share}/buildenv/rootfs/debian-bookworm"
```

3. Init your project
```
buildenv init project
```

4. Start your project
```
buildenv start project
```

Now you are there!

You can also just execute buildenv for help.

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

NixOS images use `rootfs.squashfs`. Their initialization installs `squashfs-tools`
inside the temporary Debian bootstrap container, which requires network access
to Debian package repositories. NetBSD is included in the catalogue as a
`virtual-machine` template; it provides only `disk.qcow2` and cannot run under
Docker, so initialization and startup report that limitation before creating
Docker images. Catalogue coverage does not imply every image has been boot-tested
with this tool.

The historical `debian-11` and `ubuntu-12` templates remain for existing projects,
but their releases are absent from the current index and cannot currently be
downloaded. New projects use `debian-bookworm` by default.

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
