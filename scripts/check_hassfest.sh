#!/usr/bin/env bash
# Run Home Assistant's own hassfest against this integration, without Docker.
# Uses a sparse checkout of the home-assistant/core scripts at the tag matching the
# Home Assistant version installed in .venv, and symlinks the installed package.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
WORK="${HASSFEST_DIR:-$ROOT/.hassfest}"
VERSION="$("$PY" -c 'import homeassistant.const as c; print(c.__version__)')"
SITE="$("$PY" -c 'import homeassistant, pathlib; print(pathlib.Path(homeassistant.__file__).parent)')"

if [ ! -d "$WORK/core/script" ]; then
  mkdir -p "$WORK"
  git clone --quiet --depth 1 --branch "$VERSION" --filter=blob:none --sparse \
    https://github.com/home-assistant/core.git "$WORK/core"
  git -C "$WORK/core" sparse-checkout set script
fi
ln -sfn "$SITE" "$WORK/core/homeassistant"

cd "$WORK/core"
PATH="$ROOT/.venv/bin:$PATH" "$PY" -m script.hassfest \
  --integration-path "$ROOT/custom_components/homeboard" --action validate
