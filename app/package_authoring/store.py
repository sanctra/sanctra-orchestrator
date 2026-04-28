from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class PackageStore:
    """Filesystem JSON package store for the first consultant-led runtime slice."""

    def __init__(self, root: str | Path | None = None) -> None:
        configured = root or os.getenv("SANCTRA_PACKAGE_STORE_DIR")
        self.root = Path(configured or (Path(tempfile.gettempdir()) / "sanctra-package-store"))

    def bundle_path(self, package_id: str) -> Path:
        safe_id = package_id.replace(":", "__").replace("/", "_")
        return self.root / safe_id / "bundle.json"

    def exists(self, package_id: str) -> bool:
        return self.bundle_path(package_id).exists()

    def read(self, package_id: str) -> dict[str, Any]:
        path = self.bundle_path(package_id)
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def write(self, package_id: str, bundle: dict[str, Any]) -> None:
        path = self.bundle_path(package_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(bundle, fh, indent=2, sort_keys=True)
            fh.write("\n")
        tmp.replace(path)
