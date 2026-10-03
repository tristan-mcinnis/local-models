#!/bin/sh
# Check a release DMG without launching the app.
#   sh scripts/verify-dmg.sh path/to/LocalModels-<version>-macos-arm64.dmg
# Mounts it read-only, checks the app, its signature, its architecture, its
# version against the file name and the bundled notices, then detaches.
# spctl is expected to reject an ad-hoc app; the result is printed, not judged.
set -eu

DMG="${1:?usage: verify-dmg.sh <dmg>}"
APP_NAME="Local Models"
EXEC=LocalModelsBar

fail() { echo "VERIFY FAIL: $*" >&2; exit 1; }

MNT=$(mktemp -d)
hdiutil attach -nobrowse -readonly -noautoopen -mountpoint "$MNT" "$DMG" >/dev/null
trap 'hdiutil detach "$MNT" >/dev/null 2>&1 || true; rmdir "$MNT" 2>/dev/null || true' EXIT

APP="$MNT/$APP_NAME.app"
[ -d "$APP" ] || fail "$APP_NAME.app is not in the image"
[ -L "$MNT/Applications" ] || fail "no /Applications link"
[ "$(readlink "$MNT/Applications")" = "/Applications" ] || fail "Applications link points elsewhere"
echo "ok  app and /Applications link present"

codesign --verify --strict --verbose=2 "$APP" || fail "codesign verify failed on the app"
find "$APP/Contents" \( -name '*.framework' -o -name '*.dylib' -o -name '*.xpc' \
    -o -name '*.appex' -o -name '*.app' -o -name '*.bundle' \) -print \
  | while IFS= read -r nested; do
      codesign --verify --strict --verbose=2 "$nested" || fail "codesign verify failed on $nested"
    done
echo "ok  codesign --verify --strict passes (app and nested code)"

ARCHS=$(lipo -archs "$APP/Contents/MacOS/$EXEC")
echo "ok  lipo -archs: $ARCHS"
[ "$ARCHS" = "arm64" ] || fail "expected arm64, got $ARCHS"

VERSION=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist")
case "$(basename "$DMG")" in
  LocalModels-"$VERSION"-macos-arm64.dmg) echo "ok  Info.plist version $VERSION matches the file name" ;;
  *) fail "Info.plist version $VERSION does not match $(basename "$DMG")" ;;
esac

for f in THIRD_PARTY_NOTICES.md LICENSE; do
  [ -s "$APP/Contents/Resources/$f" ] || fail "$f missing from the app bundle"
done
echo "ok  THIRD_PARTY_NOTICES.md and LICENSE are inside the app"

echo "spctl --assess (a rejection is expected for an ad-hoc app):"
spctl --assess --type execute --verbose=4 "$APP" 2>&1 | sed 's/^/    /' || true
echo "VERIFY OK: $DMG"
