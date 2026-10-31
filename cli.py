#!/usr/bin/env python3
"""
iPhone Photo Curator - CLI Interface
High-speed, safe, and intelligent organization tool for iPhone & camera photos.
"""

import os
import sys
import argparse
from datetime import datetime

# Ensure package directory is on path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from core.scanner import scan_directory
from core.organizer import build_organization_plan, execute_plan, undo_manifest

def print_banner():
    print("=" * 66)
    print("  📸  iPhone Photo Curator | 苹果照片智能整理与健康体检工具")
    print("  安全归档 · 实况配对保护 · 截屏/超大视频剥离 · 连拍去重推荐")
    print("=" * 66)

def main():
    parser = argparse.ArgumentParser(description="iPhone Photo Curator - 智能整理与健康体检")
    parser.add_argument("--src", type=str, help="源文件夹路径（待整理的照片文件夹）")
    parser.add_argument("--dest", type=str, help="整理后的输出文件夹路径（默认在源目录后加 _organized）")
    parser.add_argument("--mode", type=str, choices=["dry_run", "copy", "move"], default="dry_run",
                        help="运行模式: dry_run(预演不修改文件, 默认), copy(安全复制), move(移动)")
    parser.add_argument("--no-similarity", action="store_true", help="跳过相似图片计算以最大化扫描速度")
    parser.add_argument("--video-threshold", type=int, default=100, help="超大视频阈值(MB)，默认 100MB")
    parser.add_argument("--undo", type=str, help="撤销某次整理（输入 manifest.json 文件路径）")
    
    args = parser.parse_args()

    print_banner()

    # Handle Undo
    if args.undo:
        print(f"\n🔄 正在执行撤销回滚: {args.undo}")
        res = undo_manifest(args.undo)
        print(f"👉 结果: {res.get('message')}")
        return

    if not args.src:
        print("\n❌ 错误: 请指定 --src 文件夹路径，例如:")
        print("   python3 cli.py --src ~/Downloads/iPhonePhotos --mode dry_run")
        print("   或运行 python3 server.py 启动 Web 可视化面板交互整理。")
        sys.exit(1)

    src_dir = os.path.expanduser(args.src)
    if not os.path.isdir(src_dir):
        print(f"\n❌ 错误: 目标路径不存在或不是目录: {src_dir}")
        sys.exit(1)

    dest_dir = os.path.expanduser(args.dest) if args.dest else f"{src_dir}_organized"

    print(f"\n[1/3] 🔍 正在扫描分析目录: {src_dir}")
    print("      正在读取文件元数据、配对实况照片、识别截图...")

    report = scan_directory(
        src_dir=src_dir,
        large_video_threshold_mb=args.video_threshold,
        compute_similarity=not args.no_similarity
    )

    print("\n" + "-" * 66)
    print("📊【相册健康度体检诊断报告】")
    print("-" * 66)
    print(f"• 媒体文件总数:   {report.total_files:>6} 个")
    print(f"• 占用存储空间:   {report.total_bytes / (1024*1024*1024):>6.2f} GB ({report.total_bytes / (1024*1024):.1f} MB)")
    print(f"• 格式分布情况:   " + ", ".join([f"{k}: {v}" for k, v in report.format_counts.items()]))
    print(f"• 实况照片配对:   {report.live_photo_pairs:>6} 组 (已自动绑定保护 .HEIC + .MOV)")
    print(f"• 屏幕截图识别:   {len(report.screenshots):>6} 张 ({sum(s['size_bytes'] for s in report.screenshots)/(1024*1024):.1f} MB)")
    print(f"• 超大视频(>{args.video_threshold}MB): {len(report.large_videos):>6} 个 ({sum(v['size_bytes'] for v in report.large_videos)/(1024*1024):.1f} MB)")
    print(f"• 完全重复照片:   {len(report.exact_duplicate_groups):>6} 组")
    print(f"• 相似连拍照片:   {len(report.similar_photo_groups):>6} 组")
    print(f"• 预估可精简空间: {report.potential_freed_bytes / (1024*1024):>6.1f} MB")
    print("-" * 66)

    # Build Plan
    print(f"\n[2/3] 📐 正在规划归档路径 (目标: {dest_dir})...")
    plan = build_organization_plan(
        report=report,
        dest_dir=dest_dir,
        mode=args.mode,
        separate_screenshots=True,
        separate_large_videos=True,
        isolate_duplicates=True,
        rename_files=True
    )

    print(f"• 规划执行模式:   {args.mode.upper()}")
    print(f"• 涉及文件夹数:   {len(plan.created_folders)} 个")
    print(f"• 归档层级结构示例:")
    categories = {}
    for act in plan.actions:
        cat = act['category']
        if cat not in categories:
            categories[cat] = act['dest']
    for cat, sample in categories.items():
        rel = os.path.relpath(sample, dest_dir)
        print(f"   [{cat}] -> {rel}")

    # Execute Plan
    print(f"\n[3/3] 🚀 执行整理操作 (Mode: {args.mode})...")
    result = execute_plan(plan)

    if args.mode == "dry_run":
        print("\n💡【预演完成说明】")
        print("  当前为 dry_run 预演模式，磁盘未发生任何实际变更。")
        print(f"  如需正式执行，请加上 `--mode copy` (安全复制) 或 `--mode move` (移动)。")
        print(f"  例如: python3 cli.py --src \"{src_dir}\" --dest \"{dest_dir}\" --mode copy")
    else:
        print("\n✅【整理完成】")
        print(f"  成功: {result.get('success_count')} 个文件")
        print(f"  失败: {result.get('failed_count')} 个文件")
        print(f"  归档清单: {result.get('manifest_path')}")
        if args.mode == "move":
            print(f"  提示: 如需一键还原，可运行: python3 cli.py --undo \"{result.get('manifest_path')}\"")

if __name__ == "__main__":
    main()
