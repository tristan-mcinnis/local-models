#!/bin/sh
# Package the Local Models menu-bar app for a GitHub release.
#
# Builds the app, signs it ad hoc (no Apple Developer ID, no notarization),
# wraps it in a compressed DMG with an /Applications link, then writes
# SHA256SUMS and RELEASE_NOTES.md next to it and verifies the result.
# It never uploads anything: the last lines print the `gh release create`
# command for you to run.
#
#   sh scripts/make-dmg.sh
#   OUT_DIR=/some/dir sh scripts/make-dmg.sh      # default: dist/release
#   SIGN_IDENTITY="Developer ID Application: ..." sh scripts/make-dmg.sh
#   SKIP_BUILD=1 sh scripts/make-dmg.sh           # reuse dist/Local Models.app
#
# The DMG holds only the menu-bar app. The daemon is Python and installs
# from source (see the README).
set -eu
cd "$(dirname "$0")/.."

REPO=local-models
APP_NAME="Local Models"
FILE_BASE=LocalModels
APP="dist/$APP_NAME.app"
PLIST="$APP/Contents/Info.plist"
SIGN_IDENTITY="${SIGN_IDENTITY:--}"
OUT_DIR="${OUT_DIR:-dist/release}"
WHATS_NEW="${WHATS_NEW:-First public release of the menu-bar app.}"

[ "$(uname -m)" = "arm64" ] || { echo "make-dmg: build on Apple Silicon (arm64)" >&2; exit 1; }

if [ -z "${SKIP_BUILD:-}" ]; then
  make menubar
fi
[ -d "$APP" ] || { echo "make-dmg: $APP not found; run make menubar" >&2; exit 1; }

VERSION=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$PLIST")
DMG_NAME="$FILE_BASE-$VERSION-macos-arm64.dmg"

# Sign nested code first, deepest path first, then the app. No --deep.
if [ "$SIGN_IDENTITY" = "-" ]; then
  SIGN_OPTS="--timestamp=none"
else
  SIGN_OPTS="--timestamp --options runtime"
fi
find "$APP/Contents" \( -name '*.framework' -o -name '*.dylib' -o -name '*.xpc' \
    -o -name '*.appex' -o -name '*.app' -o -name '*.bundle' \) -print \
  | awk '{ print length($0) " " $0 }' | sort -rn | cut -d' ' -f2- \
  | while IFS= read -r nested; do
      # shellcheck disable=SC2086
      codesign --force --sign "$SIGN_IDENTITY" $SIGN_OPTS "$nested"
    done
# shellcheck disable=SC2086
codesign --force --sign "$SIGN_IDENTITY" $SIGN_OPTS "$APP"

mkdir -p "$OUT_DIR"
rm -f "$OUT_DIR/$DMG_NAME" "$OUT_DIR/SHA256SUMS" "$OUT_DIR/RELEASE_NOTES.md"

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
ditto "$APP" "$STAGE/$APP_NAME.app"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -ov -format UDZO -fs HFS+ \
  "$OUT_DIR/$DMG_NAME" >/dev/null

(cd "$OUT_DIR" && shasum -a 256 "$DMG_NAME" > SHA256SUMS)
SHA=$(cut -d' ' -f1 "$OUT_DIR/SHA256SUMS")

cat > "$OUT_DIR/RELEASE_NOTES.md" <<NOTES
# $APP_NAME $VERSION

$APP_NAME is a free, open-source menu-bar app for a Mac. It shows which local
models are warm and loads or unloads them.

## This DMG holds only the menu-bar app

The daemon is Python and is **not** in this DMG. Until you install the daemon,
the app shows it as unreachable. Install the daemon from source:

\`\`\`bash
git clone https://github.com/tristan-mcinnis/$REPO.git
cd $REPO
python3 -m pip install -r requirements.txt
make install
make install-server
\`\`\`

## What is new

$WHATS_NEW

## Requirements

- A Mac with Apple Silicon (arm64). This DMG is not universal.
- macOS 14 or later.
- The daemon, installed as above (Python 3.11 or later).

## First open (not notarized)

The app is not notarized. It is a free project and has no paid Apple Developer ID, so macOS blocks the first open. This is expected. To open it:

1. Drag the app to Applications.
2. Open it once. macOS says it cannot verify the app. Click Done.
3. Open System Settings > Privacy & Security. Scroll down and click Open Anyway. Confirm.

Or, in Terminal:

\`\`\`bash
xattr -dr com.apple.quarantine "/Applications/$APP_NAME.app"
\`\`\`

Each release is signed ad hoc. After an update, macOS may ask again for permissions such as Accessibility or Microphone.

## Checksum

\`$DMG_NAME\` sha256:

\`\`\`
$SHA
\`\`\`

Check it with \`shasum -a 256 -c SHA256SUMS\` in the download folder.
NOTES

sh scripts/verify-dmg.sh "$OUT_DIR/$DMG_NAME"

echo
echo "artifacts in $OUT_DIR:"
ls -l "$OUT_DIR"
echo
echo "Draft release (run this yourself; nothing was uploaded):"
echo "gh release create v$VERSION --repo tristan-mcinnis/$REPO --draft --title \"$APP_NAME $VERSION\" --notes-file \"$OUT_DIR/RELEASE_NOTES.md\" \"$OUT_DIR/$DMG_NAME\" \"$OUT_DIR/SHA256SUMS\""
