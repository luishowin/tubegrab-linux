#!/bin/sh
# Build a noarch Fedora RPM from the current source tree.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_DIR"

if ! command -v rpmbuild >/dev/null 2>&1; then
    echo "rpmbuild was not found. On Fedora, install it with: sudo dnf install rpm-build" >&2
    exit 1
fi

VERSION=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' tubegrab/__init__.py)
if [ -z "$VERSION" ]; then
    echo "Could not determine the TubeGrab version from tubegrab/__init__.py." >&2
    exit 1
fi

SPEC_VERSION=$(awk '$1 == "Version:" { print $2; exit }' packaging/tubegrab.spec)
if [ "$VERSION" != "$SPEC_VERSION" ]; then
    echo "Version mismatch: tubegrab/__init__.py has $VERSION but the spec has $SPEC_VERSION." >&2
    exit 1
fi

TOPDIR="${RPM_TOPDIR:-$HOME/rpmbuild}"
SOURCEDIR="$TOPDIR/SOURCES"
TARBALL="$SOURCEDIR/tubegrab-$VERSION.tar.gz"

mkdir -p "$SOURCEDIR" "$TOPDIR/SPECS" "$TOPDIR/BUILD" "$TOPDIR/RPMS" "$TOPDIR/SRPMS"
rm -f "$TARBALL"

tar --create --gzip --file "$TARBALL" \
    --transform "s,^,tubegrab-$VERSION/," \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache' \
    --exclude='.ruff_cache' \
    --exclude='dist' \
    --exclude='*.rpm' \
    --exclude='*.tar.gz' \
    tubegrab tubegrab.py desktop packaging README.md LICENSE \
    install.sh uninstall.sh tests

# rpmbuild expects an absolute spec path when its working directory changes.
rpmbuild -ba --define "_topdir $TOPDIR" "$PROJECT_DIR/packaging/tubegrab.spec"

mkdir -p "$PROJECT_DIR/dist"
cp "$TOPDIR"/RPMS/noarch/tubegrab-"$VERSION"-*.rpm "$PROJECT_DIR/dist/"

RPM_FILE=$(ls -1 "$PROJECT_DIR"/dist/tubegrab-"$VERSION"-*.rpm | head -n 1)

echo
echo "RPM written to:"
echo "  $RPM_FILE"
echo
echo "Install it with:"
echo "  sudo dnf install $RPM_FILE"
