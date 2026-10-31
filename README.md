# 📸 iPhone Photo Curator (苹果照片智能整理与健康体检工具)

为 iPhone 用户与买方投研量身打造的照片深度体检与安全归档工具。
基于 macOS 原生元数据引擎（`mdls` / `sips`）与计算机视觉算法，实现秒级海量照片扫描、实况照片成对绑定保护、截图与大视频剥离、以及基于清晰度评分的连拍去重推荐。

---

## 🌟 核心功能特性

1. **实况照片（Live Photos）成对绑定保护**：
   - 自动检测并成对绑定同名或相同 Content Identifier 的 `.HEIC` 与 `.MOV` 伴侣文件。
   - 无论是规范重命名还是跨目录归档，确保成对文件保持完全相同的新文件名，重新导入苹果设备时 100% 保持实况动效，绝不拆散。
2. **深度 EXIF / 原始时间提取与规范重命名**：
   - 调用 macOS 原生 `mdls` 批量解析 `kMDItemContentCreationDate` 与拍摄机型，绕过微信/网盘拷贝导致的文件系统伪创建时间。
   - 规范重命名格式：`YYYYMMDD_HHMMSS_{机型}_{原名}.ext`（例如 `20240915_183012_iPhone15Pro_IMG_4921.heic`）。
3. **屏幕截图智能识别与自动剥离**：
   - 结合文件名关键词、PNG 容器格式与 iPhone 视网膜屏幕物理分辨率/宽高比（19.5:9 等），准确识别截图。
   - 自动剥离至 `00_屏幕截图/` 独立目录，还主相册一片清爽。
4. **超大视频排查与空间释放**：
   - 自动检出大于 100MB（阈值可调）的 4K/长时间录像视频，归入 `01_超大视频/` 便于决策处理。
5. **相似连拍与去重智能推荐（Smart Deduplication）**：
   - 结合感知哈希（dHash）与时间窗口聚类（±30秒）。
   - 运用拉普拉斯方差（Laplacian Variance）计算图像清晰度与锐度评分，自动打标 `⭐ 推荐保留（最佳单张）`，其余连拍废片打标 `建议清理` 并放入 `02_待审与多余相似项/`，绝不盲目强删。
6. **双模式安全防护与事务撤销（Reversibility）**：
   - **预演模式 (Dry Run)**：不修改任何磁盘文件，仅输出规划图。
   - **安全复制 (Copy)**：默认模式，原文件完好无损保留在原处。
   - **事务清单 (Manifest)**：全流程记录 JSON 操作清单，支持一键撤销回滚（Undo）。

---

## 🚀 启动与使用方式

### 方式一：双击启动 Web 可视化看板（最直观推荐）
在访达（Finder）中直接双击：
```bash
~/WorkBuddy/启动iPhone照片整理器.command
```
系统将自动启动轻量后端，并在默认浏览器弹出 `http://127.0.0.1:8765` 交互式看板。
- 支持路径一键快捷填充（Pictures / Downloads / Desktop / 外接移动硬盘）；
- 实时预览重复组、截图缩略图、超大视频排行；
- 一键执行 Dry Run 预演或正式归档。

### 方式二：终端 CLI 命令行直接运行
```bash
# 1. 深度体检与预演（不修改文件）
python3 ~/WorkBuddy/iPhonePhotoCurator/cli.py --src ~/Pictures/iPhoneDump --mode dry_run

# 2. 安全复制归档
python3 ~/WorkBuddy/iPhonePhotoCurator/cli.py --src ~/Pictures/iPhoneDump --dest ~/Pictures/iPhone_Organized --mode copy

# 3. 极速模式（跳过相似度计算）
python3 ~/WorkBuddy/iPhonePhotoCurator/cli.py --src ~/Pictures/iPhoneDump --no-similarity --mode copy

# 4. 撤销回滚（移动模式下）
python3 ~/WorkBuddy/iPhonePhotoCurator/cli.py --undo ~/Pictures/iPhone_Organized/manifest_move_20261018_100000.json
```

---

## 📁 整理后的目录结构标准

```text
整理输出目录/
├── 2024/
│   ├── 2024-05/
│   │   ├── 20240501_143022_iPhone15Pro_IMG_1024.heic
│   │   └── 20240501_143022_iPhone15Pro_IMG_1024.mov  ← 实况伴侣视频同步同名保存
│   └── 2024-06/
├── 00_屏幕截图/
│   └── 2024/
│       └── 20240510_091520_Screenshot_IMG_1088.png
├── 01_超大视频/
│   └── 2024/
│       └── 20240520_190000_Video_4K_IMG_1200.mov
└── 02_待审与多余相似项/
    └── SIMILAR_001/
        ├── [建议清理]_20240502_120101_IMG_1051.heic
        └── [建议清理]_20240502_120102_IMG_1052.heic
```
