from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class BackupManager:
    def __init__(self, project_root: Path, state_dir: Path):
        self.project_root = Path(project_root)
        self.state_dir = Path(state_dir)
        self.backup_dir = self.state_dir / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def _calculate_sha256(self, path: Path) -> str:
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def create_backup(self) -> tuple[Path, dict[str, Any]]:
        """Creates a zip backup of key directories and files, generates a manifest,
        calculates checksums, and returns the backup zip path and manifest metadata.
        """
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_zip_path = self.backup_dir / f"jayu_backup_{timestamp}.zip"
        
        # Define items to backup
        targets = {
            "state": self.state_dir,
            "runs": self.project_root / "runs",
            "signals": self.project_root / "signals",
            "reports": self.project_root / "reports",
            "configs": self.project_root / "configs",
        }

        manifest: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "version": "1.0",
            "files": {},
        }

        # We will write to a temporary zip first, then move it
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_zip = Path(temp_dir) / "backup.zip"
            
            with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as zip_file:
                for target_name, target_path in targets.items():
                    if not target_path.exists():
                        continue
                    
                    if target_path.is_file():
                        # Skip if it is within backup_dir to avoid recursive backup
                        if self.backup_dir in target_path.parents or target_path == backup_zip_path:
                            continue
                        rel_path = target_path.relative_to(self.project_root)
                        zip_file.write(target_path, rel_path.as_posix())
                        checksum = self._calculate_sha256(target_path)
                        manifest["files"][rel_path.as_posix()] = {
                            "category": target_name,
                            "sha256": checksum,
                            "size": target_path.stat().st_size,
                        }
                    else:
                        for file_path in target_path.rglob("*"):
                            if file_path.is_file():
                                # Skip backups directory itself
                                if self.backup_dir in file_path.parents or file_path == backup_zip_path:
                                    continue
                                rel_path = file_path.relative_to(self.project_root)
                                zip_file.write(file_path, rel_path.as_posix())
                                checksum = self._calculate_sha256(file_path)
                                manifest["files"][rel_path.as_posix()] = {
                                    "category": target_name,
                                    "sha256": checksum,
                                    "size": file_path.stat().st_size,
                                }

                # Write manifest to zip
                manifest_content = json.dumps(manifest, indent=2, ensure_ascii=False)
                zip_file.writestr("manifest.json", manifest_content)

            # Move temporary zip to final destination
            shutil.move(str(temp_zip), str(backup_zip_path))

        # Write external checksum file
        zip_checksum = self._calculate_sha256(backup_zip_path)
        checksum_file = backup_zip_path.with_suffix(".zip.sha256")
        with open(checksum_file, "w", encoding="utf-8") as f:
            f.write(f"{zip_checksum}  {backup_zip_path.name}\n")

        manifest["backup_file"] = backup_zip_path.name
        manifest["zip_sha256"] = zip_checksum
        
        return backup_zip_path, manifest

    def restore_backup(self, backup_zip_path: Path, dry_run: bool = False) -> dict[str, Any]:
        """Validates and restores a backup zip file.
        If dry_run is True, perform validations and return expected changes without writing.
        """
        if not backup_zip_path.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_zip_path}")

        # Validate zip file integrity
        if not zipfile.is_zipfile(backup_zip_path):
            raise ValueError(f"Invalid backup file (not a zip): {backup_zip_path}")

        # Check external checksum if exists
        checksum_file = backup_zip_path.with_suffix(".zip.sha256")
        if checksum_file.exists():
            actual_checksum = self._calculate_sha256(backup_zip_path)
            with open(checksum_file, "r", encoding="utf-8") as f:
                expected_checksum = f.read().split()[0].strip()
            if actual_checksum != expected_checksum:
                raise ValueError("Backup zip file checksum mismatch. File may be corrupted.")

        report: dict[str, Any] = {
            "valid": True,
            "dry_run": dry_run,
            "manifest": {},
            "actions": [],
            "errors": [],
        }

        with zipfile.ZipFile(backup_zip_path, "r") as zip_file:
            # Read manifest
            if "manifest.json" not in zip_file.namelist():
                raise ValueError("Missing manifest.json inside the backup zip.")
            
            manifest_content = zip_file.read("manifest.json").decode("utf-8")
            manifest = json.loads(manifest_content)
            report["manifest"] = manifest

            # Verify files in zip against manifest
            for rel_path, file_meta in manifest.get("files", {}).items():
                if rel_path not in zip_file.namelist():
                    report["errors"].append(f"File {rel_path} in manifest is missing in zip archive.")
                    report["valid"] = False
                    continue
                
                # Check if target file exists and if it has changed
                dest_path = self.project_root / rel_path
                action = "create"
                if dest_path.exists():
                    action = "overwrite"
                    # Compare checksum if possible to see if it's identical
                    try:
                        current_checksum = self._calculate_sha256(dest_path)
                        if current_checksum == file_meta["sha256"]:
                            action = "skip_identical"
                    except Exception:
                        pass
                
                report["actions"].append({
                    "path": rel_path,
                    "action": action,
                    "size": file_meta["size"],
                })

            if not report["valid"]:
                return report

            # If not dry run, perform actual extraction
            if not dry_run:
                for action_item in report["actions"]:
                    if action_item["action"] == "skip_identical":
                        continue
                    
                    rel_path = action_item["path"]
                    dest_path = self.project_root / rel_path
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    # Extract single file
                    with zip_file.open(rel_path) as source_file:
                        with open(dest_path, "wb") as target_file:
                            shutil.copyfileobj(source_file, target_file)

        return report
