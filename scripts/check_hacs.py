"""Local mirror of the HACS integration rules (the CI runs the real hacs/action).

Run: python scripts/check_hacs.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOMAIN = "homeboard"
COMPONENT = ROOT / "custom_components" / DOMAIN
REQUIRED_MANIFEST = ("domain", "name", "codeowners", "documentation", "issue_tracker", "version")


def main() -> int:
    errors: list[str] = []

    def need(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    dirs = [
        p.name
        for p in (ROOT / "custom_components").iterdir()
        if p.is_dir() and p.name != "__pycache__"
    ]
    need(
        dirs == [DOMAIN],
        f"custom_components must contain exactly one integration folder, found {dirs}",
    )

    manifest_path = COMPONENT / "manifest.json"
    need(manifest_path.is_file(), "manifest.json is missing")
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    for key in REQUIRED_MANIFEST:
        need(bool(manifest.get(key)), f"manifest.json needs a non-empty '{key}'")
    need(manifest.get("domain") == DOMAIN, "manifest domain must match the folder name")
    need((COMPONENT / "__init__.py").is_file(), "__init__.py is missing")
    need(
        (COMPONENT / "config_flow.py").is_file() or not manifest.get("config_flow"),
        "config_flow.py is missing",
    )

    hacs_path = ROOT / "hacs.json"
    need(hacs_path.is_file(), "hacs.json is missing")
    hacs = json.loads(hacs_path.read_text()) if hacs_path.is_file() else {}
    need(bool(hacs.get("name")), "hacs.json needs a 'name'")
    allowed = {
        "name",
        "content_in_root",
        "zip_release",
        "filename",
        "country",
        "homeassistant",
        "persistent_directory",
        "hide_default_branch",
        "render_readme",
        "hacs",
    }
    need(set(hacs) <= allowed, f"hacs.json has unknown keys: {sorted(set(hacs) - allowed)}")

    for name in ("README.md", "LICENSE"):
        need((ROOT / name).is_file(), f"{name} is missing")
    brand = COMPONENT / "brand"
    for name in ("icon.png", "logo.png"):
        need((brand / name).is_file(), f"brand/{name} is missing")
    for name in ("strings.json", "services.yaml", "translations/en.json", "icons.json"):
        need((COMPONENT / name).is_file(), f"{name} is missing")
    for path in [*COMPONENT.rglob("*.json"), hacs_path]:
        try:
            json.loads(path.read_text())
        except (ValueError, OSError) as err:
            errors.append(f"{path.relative_to(ROOT)} is not valid JSON: {err}")
    need((ROOT / ".github" / "workflows").is_dir(), "no GitHub workflows (hassfest / hacs) found")

    strings = json.loads((COMPONENT / "strings.json").read_text())
    english = json.loads((COMPONENT / "translations" / "en.json").read_text())
    need(strings == english, "translations/en.json must equal strings.json")

    if errors:
        print("HACS checks failed:")
        for error in errors:
            print(" -", error)
        return 1
    print(f"HACS checks passed (version {manifest['version']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
