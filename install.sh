#!/usr/bin/env bash

set -euo pipefail

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
bin_dir="$HOME/.local/bin"
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/buildenv"

echo "install buildenv to $bin_dir"
install -d -m 755 "$bin_dir"
install -m 755 "$source_dir/buildenv" "$bin_dir/buildenv"

echo "install configuration to $config_dir"
install -d -m 755 "$config_dir"
for directory in projects templates; do
	install -d -m 755 "$config_dir/$directory"
	for config in "$source_dir/$directory/"*; do
		target="$config_dir/$directory/${config##*/}"
		if [ -e "$target" ] || [ -L "$target" ]; then
			echo "$target exists, skip"
		else
			install -m 644 "$config" "$target"
		fi
	done
done

echo 'install success'
case ":${PATH:-}:" in
	*:"$bin_dir":*) ;;
	*)
		echo 'Add the following line to your shell startup file, then reload it:'
		echo 'export PATH="$HOME/.local/bin:$PATH"'
		;;
esac
