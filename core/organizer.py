"""
Organizer Engine for iPhone Photo Curator.
Executes safe, non-destructive file operations (Dry-Run, Copy, Move).
Maintains Live Photo pairing, separates screenshots, and records reversible manifests.
"""

import os
import shutil
import json
from datetime import datetime
from typing import Dict, List, Any, Optional

from core.scanner import ScanReport, PhotoItem

class OrganizationPlan:
    def __init__(self, src_dir: str, dest_dir: str, mode: str = "copy"):
        self.src_dir = os.path.abspath(src_dir)
        self.dest_dir = os.path.abspath(dest_dir)
        self.mode = mode.lower() # 'copy', 'move', 'dry_run'
        self.actions: List[Dict[str, Any]] = []
        self.total_operations: int = 0
        self.total_bytes: int = 0
        self.created_folders: set = set()
        self.manifest_file: str = ""

    def add_action(
        self,
        src_path: str,
        dest_path: str,
        category: str,
        size_bytes: int,
        is_live_photo_pair: bool = False
    ):
        self.actions.append({
            "src": src_path,
            "dest": dest_path,
            "category": category,
            "size_bytes": size_bytes,
            "is_live_photo_pair": is_live_photo_pair,
            "status": "pending"
        })
        self.total_operations += 1
        self.total_bytes += size_bytes
        self.created_folders.add(os.path.dirname(dest_path))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "src_dir": self.src_dir,
            "dest_dir": self.dest_dir,
            "mode": self.mode,
            "total_operations": self.total_operations,
            "total_size_mb": round(self.total_bytes / (1024 * 1024), 2),
            "folder_count": len(self.created_folders),
            "sample_actions": self.actions[:100]
        }

def sanitize_name(name: str) -> str:
    """Sanitizes camera model or string for filename."""
    clean = "".join(c if c.isalnum() or c in ['-', '_'] else '_' for c in name)
    return clean.strip('_')

def get_unique_target_path(target_path: str, reserved_paths: set) -> str:
    """Ensures no overwrite collision by appending _1, _2 if file or reservation exists."""
    if not os.path.exists(target_path) and target_path not in reserved_paths:
        reserved_paths.add(target_path)
        return target_path

    base, ext = os.path.splitext(target_path)
    counter = 1
    while True:
        candidate = f"{base}_{counter}{ext}"
        if not os.path.exists(candidate) and candidate not in reserved_paths:
            reserved_paths.add(candidate)
            return candidate
        counter += 1

def build_organization_plan(
    report: ScanReport,
    dest_dir: str,
    mode: str = "copy",
    separate_screenshots: bool = True,
    separate_large_videos: bool = True,
    isolate_duplicates: bool = True,
    rename_files: bool = True
) -> OrganizationPlan:
    """
    Builds an execution plan according to rules.
    Maintains Live Photo pairing by binding target stems.
    """
    plan = OrganizationPlan(report.src_dir, dest_dir, mode=mode)
    reserved_targets = set()
    
    # Track paired target stems for Live Photos: (dir, stem_lower) -> new_stem
    live_photo_new_stems: Dict[str, str] = {}

    for item in report.items:
        # Determine Category and Target Folder
        created = item.created_at or datetime.now()
        year_str = created.strftime("%Y")
        ym_str = created.strftime("%Y-%m")
        
        # Determine New Filename
        date_prefix = created.strftime("%Y%m%d_%H%M%S")
        model_part = f"_{sanitize_name(item.camera_model)}" if item.camera_model else ""
        clean_stem = sanitize_name(item.stem)

        if item.is_live_photo_companion and item.live_photo_partner_path:
            # Companion video follows its paired photo's new stem
            partner_key = item.live_photo_partner_path
            new_stem = live_photo_new_stems.get(partner_key)
            if not new_stem:
                new_stem = f"{date_prefix}{model_part}_{clean_stem}" if rename_files else item.stem
                live_photo_new_stems[item.file_path] = new_stem
        else:
            new_stem = f"{date_prefix}{model_part}_{clean_stem}" if rename_files else item.stem
            live_photo_new_stems[item.file_path] = new_stem

        # Category Routing:
        # 1. Duplicates / Redundant (if isolated)
        if isolate_duplicates and not item.recommended_keep and item.duplicate_group_id:
            sub_folder = os.path.join(dest_dir, "02_待审与多余相似项", item.duplicate_group_id)
            new_filename = f"[建议清理]_{new_stem}{item.ext_lower}"
            target_path = os.path.join(sub_folder, new_filename)
            category = "duplicate_redundant"

        # 2. Screenshots
        elif separate_screenshots and item.is_screenshot:
            sub_folder = os.path.join(dest_dir, "00_屏幕截图", year_str)
            new_filename = f"{new_stem}{item.ext_lower}"
            target_path = os.path.join(sub_folder, new_filename)
            category = "screenshot"

        # 3. Large Videos (> 100MB)
        elif separate_large_videos and item.is_large_video:
            sub_folder = os.path.join(dest_dir, "01_超大视频", year_str)
            new_filename = f"{new_stem}{item.ext_lower}"
            target_path = os.path.join(sub_folder, new_filename)
            category = "large_video"

        # 4. Standard Photo / Video (Chronological YYYY/YYYY-MM)
        else:
            sub_folder = os.path.join(dest_dir, year_str, ym_str)
            new_filename = f"{new_stem}{item.ext_lower}"
            target_path = os.path.join(sub_folder, new_filename)
            category = "standard_archive"

        # Resolve Collision
        final_target = get_unique_target_path(target_path, reserved_targets)
        plan.add_action(
            src_path=item.file_path,
            dest_path=final_target,
            category=category,
            size_bytes=item.size_bytes,
            is_live_photo_pair=bool(item.live_photo_partner_path)
        )

    return plan

def execute_plan(plan: OrganizationPlan, progress_callback = None) -> Dict[str, Any]:
    """
    Executes the organization plan safely.
    Writes an organization manifest JSON for reversibility.
    """
    if plan.mode == "dry_run":
        return {
            "status": "success",
            "mode": "dry_run",
            "message": f"预演完成：共规划 {plan.total_operations} 个文件，未修改磁盘。",
            "plan": plan.to_dict()
        }

    os.makedirs(plan.dest_dir, exist_ok=True)
    success_count = 0
    failed_count = 0
    errors: List[str] = []

    for idx, act in enumerate(plan.actions):
        src = act["src"]
        dest = act["dest"]
        dest_folder = os.path.dirname(dest)
        
        if progress_callback:
            progress_callback(idx + 1, plan.total_operations, f"Processing {os.path.basename(dest)}")

        try:
            os.makedirs(dest_folder, exist_ok=True)
            if plan.mode == "move":
                shutil.move(src, dest)
            else: # default copy
                shutil.copy2(src, dest)
            act["status"] = "completed"
            success_count += 1
        except Exception as e:
            act["status"] = "failed"
            act["error"] = str(e)
            failed_count += 1
            errors.append(f"{os.path.basename(src)}: {str(e)}")

    # Write Manifest for Reversibility
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest_name = f"manifest_{plan.mode}_{timestamp}.json"
    manifest_path = os.path.join(plan.dest_dir, manifest_name)
    plan.manifest_file = manifest_path

    manifest_data = {
        "timestamp": datetime.now().isoformat(),
        "src_dir": plan.src_dir,
        "dest_dir": plan.dest_dir,
        "mode": plan.mode,
        "total_operations": plan.total_operations,
        "success_count": success_count,
        "failed_count": failed_count,
        "actions": plan.actions
    }
    
    try:
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest_data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return {
        "status": "success" if failed_count == 0 else "partial_success",
        "mode": plan.mode,
        "total_operations": plan.total_operations,
        "success_count": success_count,
        "failed_count": failed_count,
        "manifest_path": manifest_path,
        "errors": errors[:20]
    }

def undo_manifest(manifest_path: str) -> Dict[str, Any]:
    """
    Rolls back an organization operation by reversing actions recorded in manifest.
    Only applicable if mode was 'move'.
    """
    if not os.path.exists(manifest_path):
        return {"status": "error", "message": "Manifest file not found."}

    with open(manifest_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if data.get("mode") != "move":
        return {
            "status": "error",
            "message": "Only 'move' operations can be undone. For 'copy', simply delete the destination folder."
        }

    actions = data.get("actions", [])
    restored = 0
    failed = 0
    for act in actions:
        if act.get("status") == "completed":
            src = act["src"] # original place
            dest = act["dest"] # organized place
            if os.path.exists(dest):
                try:
                    os.makedirs(os.path.dirname(src), exist_ok=True)
                    shutil.move(dest, src)
                    restored += 1
                except Exception:
                    failed += 1

    return {
        "status": "success",
        "message": f"撤销完成：已成功还原 {restored} 个文件，失败 {failed} 个。"
    }
