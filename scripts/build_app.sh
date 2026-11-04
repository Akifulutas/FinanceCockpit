#!/usr/bin/env bash
# ==============================================================================
# build_app.sh — ETFCockpit Release Packaging & Ad-hoc Codesign Script
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MACOS_DIR="${PROJECT_ROOT}/macos"
BUILD_DIR="${MACOS_DIR}/.build"
RELEASE_BIN="${BUILD_DIR}/out/Products/Release/FinanceCockpit"
DIST_DIR="${PROJECT_ROOT}/dist"
APP_BUNDLE="${DIST_DIR}/FinanceCockpit.app"

echo "==> Building FinanceCockpit (Release configuration)..."
cd "${MACOS_DIR}"
swift build -c release

if [[ ! -f "${RELEASE_BIN}" ]]; then
    # Fallback path if SPM output directory differs
    RELEASE_BIN="$(find "${BUILD_DIR}" -type f -name "FinanceCockpit" -perm +111 | grep -i "release" | head -n 1 || true)"
fi

if [[ -z "${RELEASE_BIN}" || ! -f "${RELEASE_BIN}" ]]; then
    echo "ERROR: Release binary FinanceCockpit not found after build!" >&2
    exit 1
fi

echo "==> Packaging application bundle: ${APP_BUNDLE}..."
rm -rf "${APP_BUNDLE}"
mkdir -p "${APP_BUNDLE}/Contents/MacOS"
mkdir -p "${APP_BUNDLE}/Contents/Resources"

cp "${RELEASE_BIN}" "${APP_BUNDLE}/Contents/MacOS/FinanceCockpit"
chmod +x "${APP_BUNDLE}/Contents/MacOS/FinanceCockpit"

echo "==> Writing Info.plist..."
cat << 'EOF' > "${APP_BUNDLE}/Contents/Info.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>en</string>
    <key>CFBundleExecutable</key>
    <string>FinanceCockpit</string>
    <key>CFBundleIdentifier</key>
    <string>com.finance.cockpit</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>FinanceCockpit</string>
    <key>CFBundleDisplayName</key>
    <string>FinanceCockpit</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSMinimumSystemVersion</key>
    <string>14.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSSupportsAutomaticGraphicsSwitching</key>
    <true/>
    <key>NSPrincipalClass</key>
    <string>NSApplication</string>
</dict>
</plist>
EOF

echo "==> Performing ad-hoc code signature..."
codesign -s - --force --deep "${APP_BUNDLE}"

echo "==> Verifying signature..."
codesign --verify --deep --strict --verbose=2 "${APP_BUNDLE}"

echo "✓ FinanceCockpit.app packaged and signed successfully at: ${APP_BUNDLE}"
