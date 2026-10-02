#!/bin/sh
# Builds baseline-desktop_<version>_all.deb from this repo into the directory given as $1 (default: ./dist).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
out=${1:-$repo/dist}
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
install -d -m 755 "$stage/DEBIAN" "$stage/opt/baseline/lib" "$stage/opt/baseline/bin" \
  "$stage/usr/share/applications" "$stage/usr/share/icons/hicolor/scalable/apps"
install -m 644 "$here/DEBIAN/control" "$stage/DEBIAN/control"
install -m 644 "$repo"/baseline/lib/*.py "$stage/opt/baseline/lib/"
install -m 755 "$repo/baseline/bin/baseline-launcher" "$repo/baseline/bin/baseline-web" "$stage/opt/baseline/bin/"
install -m 644 "$repo/packaging/baseline-launcher/baseline.desktop" "$stage/usr/share/applications/baseline.desktop"
install -m 644 "$repo/packaging/baseline-launcher/baseline.svg" "$stage/usr/share/icons/hicolor/scalable/apps/baseline.svg"
find "$stage" -type d -exec chmod 755 {} +
mkdir -p "$out"
fakeroot dpkg-deb --build "$stage" "$out/baseline-desktop_0.2.0_all.deb"
