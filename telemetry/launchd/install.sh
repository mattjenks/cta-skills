#!/bin/sh
# Install the CTA launchd agents for the current user. Substitutes __REPO__ and __HOME__.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
agents="$HOME/Library/LaunchAgents"
mkdir -p "$agents" "$HOME/.local/share/cta/logs"
for plist in "$here"/net.cta.*.plist; do
  name=$(basename "$plist")
  sed -e "s|__REPO__|$repo|g" -e "s|__HOME__|$HOME|g" "$plist" > "$agents/$name"
  launchctl bootout "gui/$(id -u)/${name%.plist}" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$agents/$name"
  echo "installed ${name%.plist}"
done
