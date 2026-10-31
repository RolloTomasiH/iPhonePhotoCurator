"""
Scanner Engine for iPhone Photo Curator.
Analyzes directories, pairs Live Photos, parses EXIF/macOS metadata,
identifies screenshots, large videos, and clusters similar/duplicate photos.
"""

import os
import re
import subprocess
from datetime import datetime
from typing import Dict, List, Any, Optional
from PIL import Image, ExifTags

from core.hasher import (
    get_file_fast_hash,
    get_full_file_md5,
    load_grayscale_matrix,
    compute_dhash,
    hamming_distance,
    compute_sharpness
)

IMAGE_EXTENSIONS = {'.heic', '.jpg', '.jpeg', '.png', '.dng', '.gif', '.webp', '.tiff', '.bmp'}
VIDEO_EXTENSIONS = {'.mov', '.mp4', '.m4v'}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

# Common iPhone Screen aspect ratios and portrait resolutions (width x height)
IPHONE_SCREEN_RESOLUTIONS = {
    (1170, 2532), (2532, 1170), # iPhone 12/13/14
    (1179, 2556), (2556, 1179), # iPhone 14 Pro / 15 / 15 Pro / 16
    (1290, 2796), (2796, 1290), # iPhone 14 Pro Max / 15 Plus / 15 Pro Max / 16 Plus
    (1206, 2622), (2622, 1206), # iPhone 16 Pro
    (1320, 2868), (2868, 1320), # iPhone 16 Pro Max
    (1284, 2778), (2778, 1284), # iPhone 12/13 Pro Max, 14 Plus
    (1242, 2688), (2688, 1242), # iPhone XS Max / 11 Pro Max
    (1125, 2436), (2436, 1125), # iPhone X / XS / 11 Pro
    (1080, 2340), (2340, 1080), # iPhone 12/13 mini
    (828, 1792),  (1792, 828),  # iPhone XR / 11
    (750, 1334),  (1334, 750),  # iPhone 7 / 8 / SE2 / SE3
    (1080, 1920), (1920, 1080), # iPhone 6/7/8 Plus
}

class PhotoItem:
    def __init__(self, file_path: str):
        self.file_path = os.path.abspath(file_path)
        self.dir_name = os.path.dirname(self.file_path)
        self.file_name = os.path.basename(self.file_path)
        self.stem, self.ext = os.path.splitext(self.file_name)
        self.ext_lower = self.ext.lower()
        
        self.size_bytes = os.path.getsize(self.file_path)
        self.is_video = self.ext_lower in VIDEO_EXTENSIONS
        self.is_image = self.ext_lower in IMAGE_EXTENSIONS
        
        # Metadata fields
        self.created_at: Optional[datetime] = None
        self.camera_model: str = ""
        self.width: int = 0
        self.height: int = 0
        self.duration_seconds: float = 0.0
        
        # Categorization tags
        self.is_live_photo_companion: bool = False
        self.live_photo_partner_path: Optional[str] = None
        self.is_screenshot: bool = False
        self.is_large_video: bool = False
        
        # Hashing & Quality
        self.fast_hash: str = ""
        self.full_md5: str = ""
        self.dhash: str = ""
        self.sharpness: float = 0.0
        self.recommended_keep: bool = True
        self.duplicate_group_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.file_path,
            "filename": self.file_name,
            "stem": self.stem,
            "ext": self.ext_lower,
            "size_bytes": self.size_bytes,
            "size_mb": round(self.size_bytes / (1024 * 1024), 2),
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else "",
            "year_month": self.created_at.strftime("%Y-%m") if self.created_at else "Unknown",
            "year": self.created_at.strftime("%Y") if self.created_at else "Unknown",
            "camera_model": self.camera_model,
            "resolution": f"{self.width}x{self.height}" if self.width and self.height else "",
            "is_video": self.is_video,
            "is_image": self.is_image,
            "is_live_photo_companion": self.is_live_photo_companion,
            "is_screenshot": self.is_screenshot,
            "is_large_video": self.is_large_video,
            "sharpness": round(self.sharpness, 1),
            "recommended_keep": self.recommended_keep,
            "duplicate_group_id": self.duplicate_group_id
        }

def batch_parse_metadata(items: List[PhotoItem], chunk_size: int = 100) -> None:
    """Batch parses creation date, camera model, and dimensions using macOS mdls plist."""
    import plistlib
    for i in range(0, len(items), chunk_size):
        chunk = items[i:i + chunk_size]
        paths = [it.file_path for it in chunk]
        try:
            cmd = [
                'mdls', '-plist', '-',
                '-name', 'kMDItemContentCreationDate',
                '-name', 'kMDItemAcquisitionModel',
                '-name', 'kMDItemPixelWidth',
                '-name', 'kMDItemPixelHeight',
                '-name', 'kMDItemDurationSeconds'
            ] + paths
            res = subprocess.run(cmd, capture_output=True, timeout=10)
            if res.returncode == 0 and res.stdout:
                parsed_list = plistlib.loads(res.stdout)
                for it, meta in zip(chunk, parsed_list):
                    if isinstance(meta, dict):
                        dt = meta.get('kMDItemContentCreationDate')
                        if isinstance(dt, datetime):
                            it.created_at = dt
                        model = meta.get('kMDItemAcquisitionModel')
                        if model:
                            it.camera_model = str(model).strip()
                        w = meta.get('kMDItemPixelWidth')
                        if w:
                            it.width = int(w)
                        h = meta.get('kMDItemPixelHeight')
                        if h:
                            it.height = int(h)
                        dur = meta.get('kMDItemDurationSeconds')
                        if dur:
                            it.duration_seconds = float(dur)
        except Exception:
            pass

def parse_exif_fallback(item: PhotoItem) -> None:
    """Fallback EXIF parsing via PIL for images."""
    if not item.is_image:
        return
    try:
        with Image.open(item.file_path) as im:
            if not item.width:
                item.width = im.width
            if not item.height:
                item.height = im.height
                
            exif = im.getexif()
            if exif:
                # 306: DateTime, 36867: DateTimeOriginal, 36868: DateTimeDigitized
                dt_str = exif.get(36867) or exif.get(36868) or exif.get(306)
                if dt_str and not item.created_at:
                    try:
                        item.created_at = datetime.strptime(str(dt_str)[:19], "%Y:%m:%d %H:%M:%S")
                    except Exception:
                        pass
                # 272: Model
                if not item.camera_model and exif.get(272):
                    item.camera_model = str(exif.get(272)).strip()
    except Exception:
        pass

def check_is_screenshot(item: PhotoItem) -> bool:
    """Checks whether an item is likely an iOS screenshot."""
    name_lower = item.file_name.lower()
    if any(keyword in name_lower for keyword in ['screenshot', 'screen_shot', '屏幕截图', '截屏', '屏幕快照']):
        return True
    
    # PNG with no camera model and matching screen resolution / aspect ratio
    if item.ext_lower == '.png':
        if not item.camera_model:
            dims = (item.width, item.height)
            if dims in IPHONE_SCREEN_RESOLUTIONS:
                return True
            if item.width > 0 and item.height > 0:
                ratio = max(item.width, item.height) / min(item.width, item.height)
                # Modern iPhone ratios are ~2.16 (19.5:9) or ~1.77 (16:9)
                if abs(ratio - 2.164) < 0.05 or abs(ratio - 1.777) < 0.05:
                    return True
    return False

class ScanReport:
    def __init__(self, src_dir: str):
        self.src_dir = os.path.abspath(src_dir)
        self.items: List[PhotoItem] = []
        self.total_files: int = 0
        self.total_bytes: int = 0
        self.format_counts: Dict[str, int] = {}
        self.format_bytes: Dict[str, int] = {}
        self.timeline_counts: Dict[str, int] = {}
        self.camera_models: Dict[str, int] = {}
        
        self.live_photo_pairs: int = 0
        self.screenshots: List[Dict[str, Any]] = []
        self.large_videos: List[Dict[str, Any]] = []
        
        self.exact_duplicate_groups: List[List[Dict[str, Any]]] = []
        self.similar_photo_groups: List[List[Dict[str, Any]]] = []
        self.potential_freed_bytes: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "src_dir": self.src_dir,
            "total_files": self.total_files,
            "total_size_mb": round(self.total_bytes / (1024 * 1024), 2),
            "total_size_gb": round(self.total_bytes / (1024 * 1024 * 1024), 2),
            "format_counts": self.format_counts,
            "format_bytes": self.format_bytes,
            "timeline_counts": dict(sorted(self.timeline_counts.items())),
            "camera_models": dict(sorted(self.camera_models.items(), key=lambda x: x[1], reverse=True)),
            "live_photo_pairs": self.live_photo_pairs,
            "screenshots_count": len(self.screenshots),
            "screenshots_mb": round(sum(s['size_bytes'] for s in self.screenshots) / (1024 * 1024), 2),
            "screenshots": self.screenshots[:200], # return first 200 for preview
            "large_videos_count": len(self.large_videos),
            "large_videos_mb": round(sum(v['size_bytes'] for v in self.large_videos) / (1024 * 1024), 2),
            "large_videos": self.large_videos,
            "exact_duplicate_groups_count": len(self.exact_duplicate_groups),
            "exact_duplicate_groups": self.exact_duplicate_groups,
            "similar_groups_count": len(self.similar_photo_groups),
            "similar_photo_groups": self.similar_photo_groups,
            "potential_freed_mb": round(self.potential_freed_bytes / (1024 * 1024), 2)
        }

def scan_directory(
    src_dir: str,
    large_video_threshold_mb: int = 100,
    compute_similarity: bool = True,
    progress_callback = None
) -> ScanReport:
    """
    Scans a directory recursively, analyzing all media files.
    """
    report = ScanReport(src_dir)
    if not os.path.exists(src_dir) or not os.path.isdir(src_dir):
        return report

    raw_items: List[PhotoItem] = []
    # Key: (dir_path, stem_lower) -> {'image': item, 'video': item}
    stem_map: Dict[tuple, Dict[str, PhotoItem]] = {}

    # Step 1: Collect all media files
    for root, _, files in os.walk(src_dir):
        # Ignore trash / hidden system folders
        if any(part.startswith('.') or part in ['$RECYCLE.BIN', '__MACOSX'] for part in root.split(os.sep)):
            continue
            
        for f in files:
            if f.startswith('.'):
                continue
            ext = os.path.splitext(f)[1].lower()
            if ext in MEDIA_EXTENSIONS:
                file_path = os.path.join(root, f)
                try:
                    item = PhotoItem(file_path)
                    raw_items.append(item)
                    
                    key = (item.dir_name, item.stem.lower())
                    if key not in stem_map:
                        stem_map[key] = {}
                    if item.is_image:
                        stem_map[key]['image'] = item
                    elif item.is_video:
                        stem_map[key]['video'] = item
                except Exception:
                    pass

    total = len(raw_items)
    report.total_files = total

    # Step 2: Pair Live Photos (Image + Companion .MOV)
    for (d, stem_lower), pair in stem_map.items():
        if 'image' in pair and 'video' in pair:
            img = pair['image']
            vid = pair['video']
            # Only pair if video is .mov (standard Apple Live Photo)
            if vid.ext_lower == '.mov':
                vid.is_live_photo_companion = True
                vid.live_photo_partner_path = img.file_path
                img.live_photo_partner_path = vid.file_path
                report.live_photo_pairs += 1

    # Step 3: Parse metadata and classify
    batch_parse_metadata(raw_items, chunk_size=100)
    for idx, item in enumerate(raw_items):
        if progress_callback:
            progress_callback(idx + 1, total, f"Classifying {item.file_name}")

        if not item.created_at:
            parse_exif_fallback(item)
        if not item.created_at:
            # Fallback to filesystem mtime
            try:
                item.created_at = datetime.fromtimestamp(os.path.getmtime(item.file_path))
            except Exception:
                item.created_at = datetime.now()

        # Update report totals
        report.total_bytes += item.size_bytes
        ext_key = item.ext_lower.upper().lstrip('.')
        report.format_counts[ext_key] = report.format_counts.get(ext_key, 0) + 1
        report.format_bytes[ext_key] = report.format_bytes.get(ext_key, 0) + item.size_bytes
        
        ym = item.created_at.strftime("%Y-%m")
        report.timeline_counts[ym] = report.timeline_counts.get(ym, 0) + 1
        
        if item.camera_model:
            report.camera_models[item.camera_model] = report.camera_models.get(item.camera_model, 0) + 1

        # Check Screenshot
        if item.is_image and check_is_screenshot(item):
            item.is_screenshot = True
            report.screenshots.append(item.to_dict())

        # Check Large Video (ignore Live Photo companion videos from large video list unless very big)
        if item.is_video and not item.is_live_photo_companion:
            if item.size_bytes >= large_video_threshold_mb * 1024 * 1024:
                item.is_large_video = True
                report.large_videos.append(item.to_dict())

    # Sort large videos descending by size
    report.large_videos.sort(key=lambda x: x['size_bytes'], reverse=True)
    report.items = raw_items

    # Step 4: Duplicate & Similarity Detection
    if compute_similarity and len(raw_items) > 1:
        _detect_duplicates_and_similarity(report, progress_callback)

    return report

def _detect_duplicates_and_similarity(report: ScanReport, progress_callback = None) -> None:
    """Detects exact duplicates and visual burst/similar groups."""
    # 4.1 Exact Duplicates by fast hash -> full md5
    hash_groups: Dict[str, List[PhotoItem]] = {}
    for item in report.items:
        # Live photo companion videos follow their photo
        if item.is_live_photo_companion:
            continue
        h = get_file_fast_hash(item.file_path)
        if h:
            item.fast_hash = h
            hash_groups.setdefault(h, []).append(item)

    exact_groups: List[List[PhotoItem]] = []
    for h, items in hash_groups.items():
        if len(items) > 1:
            # Check full MD5 to guarantee 100% exact match
            md5_map: Dict[str, List[PhotoItem]] = {}
            for it in items:
                it.full_md5 = get_full_file_md5(it.file_path)
                md5_map.setdefault(it.full_md5, []).append(it)
            for md5_val, sub_items in md5_map.items():
                if len(sub_items) > 1:
                    exact_groups.append(sub_items)

    group_idx = 1
    for grp in exact_groups:
        gid = f"EXACT_{group_idx:03d}"
        group_idx += 1
        # Pick the one with cleanest path / shortest name as keep
        grp.sort(key=lambda x: (len(x.file_name), x.file_path))
        grp[0].recommended_keep = True
        grp[0].duplicate_group_id = gid
        for it in grp[1:]:
            it.recommended_keep = False
            it.duplicate_group_id = gid
            report.potential_freed_bytes += it.size_bytes
        report.exact_duplicate_groups.append([it.to_dict() for it in grp])

    # 4.2 Perceptual Similarity for images (Bursts / Consecutive shots)
    # Filter candidates: images that are not exact duplicates and not screenshots
    image_candidates = [
        it for it in report.items 
        if it.is_image and not it.duplicate_group_id and not it.is_screenshot
    ]
    # Sort by creation time
    image_candidates.sort(key=lambda x: x.created_at)

    # Compute dHash and sharpness for candidates
    total_cand = len(image_candidates)
    for idx, it in enumerate(image_candidates):
        if progress_callback:
            progress_callback(idx + 1, total_cand, f"Hashing {it.file_name}")
        mat = load_grayscale_matrix(it.file_path, target_width=128)
        if mat is not None:
            it.dhash = compute_dhash(mat, hash_size=8)
            it.sharpness = compute_sharpness(mat)

    # Cluster consecutive images taken within 30s with Hamming distance <= 5
    visited = set()
    similar_clusters: List[List[PhotoItem]] = []

    for i in range(total_cand):
        if i in visited:
            continue
        item_a = image_candidates[i]
        if not item_a.dhash:
            continue
            
        cluster = [item_a]
        # Look ahead up to 20 photos or 60 seconds
        for j in range(i + 1, min(i + 20, total_cand)):
            if j in visited:
                continue
            item_b = image_candidates[j]
            if not item_b.dhash:
                continue
                
            time_diff = abs((item_b.created_at - item_a.created_at).total_seconds())
            if time_diff > 45: # Beyond 45 seconds, not a burst/consecutive scene
                break
                
            dist = hamming_distance(item_a.dhash, item_b.dhash)
            if dist <= 5: # Visual similarity threshold
                cluster.append(item_b)
                visited.add(j)

        if len(cluster) > 1:
            visited.add(i)
            similar_clusters.append(cluster)

    # For each similar cluster: pick highest sharpness as recommended keep
    sim_idx = 1
    for cluster in similar_clusters:
        gid = f"SIMILAR_{sim_idx:03d}"
        sim_idx += 1
        # Score = sharpness * 0.7 + (width * height / 1e6) * 0.3
        for it in cluster:
            it.duplicate_group_id = gid
            
        cluster.sort(
            key=lambda x: (x.sharpness * 0.7 + (x.width * x.height / 1000000.0) * 0.3),
            reverse=True
        )
        # Top 1 is recommended keep
        cluster[0].recommended_keep = True
        for it in cluster[1:]:
            it.recommended_keep = False
            report.potential_freed_bytes += it.size_bytes
            
        report.similar_photo_groups.append([it.to_dict() for it in cluster])
