#!/bin/sh
# Remove the CTA launchd agents for the current user.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
for plist in "$here"/net.cta.*.plist; do
  name=$(basename "$plist")
  launchctl bootout "gui/$(id -u)/${name%.plist}" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/$name"
  echo "removed ${name%.plist}"
done
