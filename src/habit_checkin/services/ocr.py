"""离线 OCR：优先使用 PaddleOCR PP-OCRv5（准确率更高），失败时回退 WinRT OCR。

- PaddleOCR 模型目录默认为项目 data/models（目录使用模型本身名字），
  可通过 HABIT_OCR_MODEL_DIR / HABIT_OCR_MODEL_ROOT 环境变量或设置页覆盖。
- 初始化失败或模型目录缺失时自动回退 Windows 自带 WinRT OCR（简体中文优先）。
- OCR 结果仅作预填，由用户确认/编辑。
"""
from __future__ import annotations

import os
import re
import tempfile
import threading
from pathlib import Path

# 这些环境变量必须在导入 paddleocr 之前设置，因此放在模块顶部。
os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "BOS")
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "False")

from habit_checkin.services.powershell import run_powershell_script

_PADDLE_LOCK = threading.Lock()
_PADDLE_OCR = None
_PADDLE_INIT_ERROR = None
_PADDLE_INIT_DEVICE = None
_PADDLE_STRUCTURE_LOCK = threading.Lock()
_PADDLE_STRUCTURE = None
_PADDLE_STRUCTURE_INIT_ERROR = None
_PADDLE_STRUCTURE_INIT_DEVICE = None


def default_model_root():
    """默认模型目录：项目根目录 data/models。"""
    return str(Path(__file__).resolve().parent.parent.parent.parent / "data" / "models")


def _resolve_model_root():
    """返回当前生效的模型根目录，优先使用环境变量/设置页配置。"""
    root = os.environ.get("HABIT_OCR_MODEL_DIR") or os.environ.get("HABIT_OCR_MODEL_ROOT")
    if root:
        root = str(root).strip().strip('"').strip("'")
        if root:
            return root
    return default_model_root()


def set_model_root(root):
    """设置 OCR 模型根目录；传空值恢复默认目录。"""
    root = (str(root).strip().strip('"').strip("'") if root else "") or ""
    if root:
        os.environ["HABIT_OCR_MODEL_DIR"] = root
    else:
        os.environ.pop("HABIT_OCR_MODEL_DIR", None)
        os.environ.pop("HABIT_OCR_MODEL_ROOT", None)
    reset_paddle_engines()


def _paddle_device():
    """当前生效的 Paddle 识别设备：cpu / gpu（设置页用 cuda 表示 GPU）。"""
    value = (os.environ.get("HABIT_OCR_DEVICE") or "cpu").strip().lower()
    return "gpu" if value in ("cuda", "gpu") else "cpu"


def set_device(device):
    """设置 Paddle 识别设备：cpu / cuda。切换后下一次识别按新设备初始化。"""
    device = (device or "").strip().lower()
    device = "cuda" if device in ("cuda", "gpu") else "cpu"
    if device == "cuda":
        os.environ["HABIT_OCR_DEVICE"] = "cuda"
    else:
        os.environ.pop("HABIT_OCR_DEVICE", None)
    reset_paddle_engines()


def set_engine(engine):
    """设置识别引擎：paddle / winrt。切换后下一次识别按新引擎初始化。"""
    engine = (engine or "").strip().lower()
    if engine == "winrt":
        os.environ["HABIT_OCR_ENGINE"] = "winrt"
    else:
        os.environ.pop("HABIT_OCR_ENGINE", None)
    reset_paddle_engines()


def reset_paddle_engines():
    """清除 Paddle 单例缓存，使模型目录/引擎/设备变更立即生效。"""
    global _PADDLE_OCR, _PADDLE_INIT_ERROR, _PADDLE_INIT_DEVICE
    global _PADDLE_STRUCTURE, _PADDLE_STRUCTURE_INIT_ERROR, _PADDLE_STRUCTURE_INIT_DEVICE
    with _PADDLE_LOCK:
        _PADDLE_OCR = None
        _PADDLE_INIT_ERROR = None
        _PADDLE_INIT_DEVICE = None
    with _PADDLE_STRUCTURE_LOCK:
        _PADDLE_STRUCTURE = None
        _PADDLE_STRUCTURE_INIT_ERROR = None
        _PADDLE_STRUCTURE_INIT_DEVICE = None


def apply_model_dir_from_setting(db):
    """启动时把数据库里的 OCR 模型目录、引擎、设备配置写入环境变量。"""
    if not hasattr(db, "get_setting"):
        return
    set_model_root(db.get_setting("ocr_model_dir", ""))
    set_engine(db.get_setting("ocr_engine", "paddle"))
    set_device(db.get_setting("ocr_device", "cpu"))


def _paddle_dirs():
    root = _resolve_model_root()
    return (
        root,
        os.path.join(root, "PP-OCRv5_server_det"),
        os.path.join(root, "PP-OCRv5_server_rec"),
        os.path.join(root, "PicoDet-S_layout_17cls"),
    )


def _prepare_paddle_env():
    root = _resolve_model_root()
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", root)
    os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "BOS")
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "False")

_PS1 = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
$path = $args[0]
try {
  [void][Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
  [void][Windows.Storage.Streams.IRandomAccessStream,Windows.Storage,ContentType=WindowsRuntime]
  [void][Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
  [void][Windows.Graphics.Imaging.SoftwareBitmap,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
  [void][Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
  [void][Windows.Media.Ocr.OcrResult,Windows.Foundation,ContentType=WindowsRuntime]
  [void][Windows.Media.Ocr.OcrLine,Windows.Foundation,ContentType=WindowsRuntime]
  [void][Windows.Globalization.Language,Windows.Globalization,ContentType=WindowsRuntime]
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
  function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
  }
  $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
  $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
  $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  $lang = New-Object Windows.Globalization.Language("zh-Hans")
  $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
  if ($null -eq $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
  if ($null -eq $engine) { Write-Output "__NO_ENGINE__"; exit 0 }
  $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
  Write-Output ("__OCR__:" + $result.Text)
  foreach ($line in $result.Lines) {
    Write-Output ("__LINEY__:" + [int]$line.BoundingRect.X + "," + [int]$line.BoundingRect.Y)
    Write-Output ("__LINE__:" + $line.Text)
  }
} catch {
  Write-Output ("__ERR__:" + $_.Exception.Message)
}
"""

_CJK_CHAR = r"[\u3400-\u4dbf\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]"
_CN_OR_DIGIT = r"[\u3400-\u4dbf\u4e00-\u9fff\u3000-\u303f\uff00-\uffef0-9]"
_CJK_SPACE_RE = re.compile("({})\\s+({})".format(_CN_OR_DIGIT, _CN_OR_DIGIT))


def cleanup_cjk_spaces(text):
    """去掉中文/数字之间的空格（WinRT OCR 常在字符间插入空格）。"""
    text = (text or "").strip()
    prev = None
    while prev != text:
        prev = text
        text = _CJK_SPACE_RE.sub(lambda m: m.group(1) + m.group(2), text)
    return text


def preprocess_for_ocr(path, keep_marks=False):
    """OCR 前预处理（颜色差分为突破口）：
    keep_marks=False：去除红笔/彩笔书写与圈画痕迹（高饱和度/偏红像素 → 白色）
    keep_marks=True ：保留红笔/手写标注（资料分析等需要识别圈量与笔记时用）
    随后统一：灰度 + 放大（长边到 1600 附近）+ 自动对比度。
    """
    import numpy as np
    from PIL import Image, ImageOps
    img = Image.open(path).convert("RGB")
    arr = np.asarray(img).astype(np.int16)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    max_rgb = np.maximum(np.maximum(r, g), b)
    min_rgb = np.minimum(np.minimum(r, g), b)
    sat = max_rgb - min_rgb  # 饱和度
    red_mask = (r - np.maximum(g, b)) > 50   # 明显偏红
    colorful = sat > 90                       # 高饱和彩笔/荧光笔
    gray = (0.299 * r + 0.587 * g + 0.114 * b).astype(np.uint8)
    if not keep_marks:
        gray[red_mask | colorful] = 255       # 笔迹区域置白（自动对比度负责背景归一）
    out = Image.fromarray(gray)
    if max(out.size) < 1600:
        scale = min(2.0, 1600.0 / max(out.size))
        if scale > 1.01:
            out = out.resize((int(out.size[0] * scale), int(out.size[1] * scale)), Image.LANCZOS)
    out = ImageOps.autocontrast(out)
    fd, tmp_path = tempfile.mkstemp(prefix="habit_ocr_pre_", suffix=".png")
    os.close(fd)
    try:
        out.save(tmp_path, "PNG")
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
    return tmp_path


def _remove_temp_file(path):
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


def _run_ocr(path, timeout=20):
    """运行 WinRT OCR，返回识别到的原始行列表；失败返回 None。"""
    try:
        proc = run_powershell_script(_PS1, str(path), timeout=timeout)
        if proc is None:
            return None
        out = proc.stdout or ""
        lines = []
        saw_result = False
        cur_xy = (0, 0)
        for raw in out.splitlines():
            line = raw.strip()
            if line.startswith("__LINEY__:"):
                parts = line[len("__LINEY__:"):].split(",")
                try:
                    cur_xy = (int(parts[0]), int(parts[1]))
                except (ValueError, IndexError):
                    cur_xy = (0, 0)
            elif line.startswith("__LINE__:"):
                lines.append((cur_xy[0], cur_xy[1], line[len("__LINE__:"):]))
                saw_result = True
            elif line.startswith("__OCR__:"):
                saw_result = True
            elif line.startswith(("__NO_ENGINE__", "__ERR__")):
                return None
        return lines if saw_result else None
    except Exception:
        return None


def _paddle_models_ready():
    """检测 PaddleOCR 两个模型目录是否已就绪（防止首次调用时误触发下载）。"""
    root, det_dir, rec_dir, _layout_dir = _paddle_dirs()
    return (
        bool(root)
        and os.path.isdir(det_dir)
        and os.path.isdir(rec_dir)
        and any(
            os.path.isfile(os.path.join(det_dir, name))
            for name in ("inference.pdmodel", "inference.pdiparams", "model.pdmodel")
        )
        and any(
            os.path.isfile(os.path.join(rec_dir, name))
            for name in ("inference.pdmodel", "inference.pdiparams", "model.pdmodel")
        )
    )


def _init_paddle_ocr(device):
    _prepare_paddle_env()
    _root, det_dir, rec_dir, _layout_dir = _paddle_dirs()
    from paddleocr import PaddleOCR
    return PaddleOCR(
        text_detection_model_name="PP-OCRv5_server_det",
        text_detection_model_dir=det_dir,
        text_recognition_model_name="PP-OCRv5_server_rec",
        text_recognition_model_dir=rec_dir,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        device=device,
    )


def _get_paddle_ocr():
    """惰性初始化 PaddleOCR 单例；设备切换或 CUDA 失败时自动重建/回退 CPU。"""
    global _PADDLE_OCR, _PADDLE_INIT_ERROR, _PADDLE_INIT_DEVICE
    device = _paddle_device()
    if _PADDLE_OCR is not None and _PADDLE_INIT_DEVICE == device:
        return _PADDLE_OCR
    if _PADDLE_INIT_ERROR is not None and _PADDLE_INIT_DEVICE == device:
        return None
    if not _paddle_models_ready():
        _PADDLE_INIT_DEVICE = device
        _PADDLE_INIT_ERROR = "PaddleOCR 模型目录不存在或缺少模型文件"
        return None
    with _PADDLE_LOCK:
        if _PADDLE_OCR is not None and _PADDLE_INIT_DEVICE == device:
            return _PADDLE_OCR
        try:
            engine = _init_paddle_ocr(device)
            _PADDLE_OCR = engine
            _PADDLE_INIT_DEVICE = device
            _PADDLE_INIT_ERROR = None
            return engine
        except Exception as exc:  # 初始化失败时回退 WinRT，不阻塞用户
            _PADDLE_INIT_DEVICE = device
            if device == "gpu":
                # CUDA 不可用（缺少 paddlepaddle-gpu / 驱动 / 显存）时自动回退 CPU，
                # 不缓存失败状态，保证下次识别直接走 CPU。
                os.environ["HABIT_OCR_DEVICE"] = "cpu"
                _PADDLE_OCR = None
                _PADDLE_INIT_DEVICE = None
                _PADDLE_INIT_ERROR = None
                try:
                    engine = _init_paddle_ocr("cpu")
                    _PADDLE_OCR = engine
                    _PADDLE_INIT_DEVICE = "cpu"
                    return engine
                except Exception as cpu_exc:
                    _PADDLE_INIT_DEVICE = "cpu"
                    _PADDLE_INIT_ERROR = "PaddleOCR 初始化失败：{}".format(cpu_exc)
                    return None
            _PADDLE_INIT_ERROR = str(exc)
            return None


def _paddle_layout_ready():
    """检测 PP-StructureV3 布局模型是否已就绪（防止首次调用时误触发下载）。"""
    _root, _det_dir, _rec_dir, layout_dir = _paddle_dirs()
    return (
        os.path.isdir(layout_dir)
        and any(
            os.path.isfile(os.path.join(layout_dir, name))
            for name in ("inference.pdmodel", "inference.pdiparams", "model.pdmodel")
        )
    )


def _init_paddle_structure(device):
    _prepare_paddle_env()
    _root, det_dir, rec_dir, layout_dir = _paddle_dirs()
    from paddleocr import PPStructureV3
    return PPStructureV3(
        layout_detection_model_name="PicoDet-S_layout_17cls",
        layout_detection_model_dir=layout_dir,
        text_detection_model_name="PP-OCRv5_server_det",
        text_detection_model_dir=det_dir,
        text_recognition_model_name="PP-OCRv5_server_rec",
        text_recognition_model_dir=rec_dir,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        use_seal_recognition=False,
        use_table_recognition=False,
        use_formula_recognition=False,
        use_chart_recognition=False,
        use_region_detection=False,
        device=device,
    )


def _get_paddle_structure():
    """惰性初始化 PP-StructureV3 单例；设备切换或 CUDA 失败时自动重建/回退 CPU。"""
    global _PADDLE_STRUCTURE, _PADDLE_STRUCTURE_INIT_ERROR, _PADDLE_STRUCTURE_INIT_DEVICE
    device = _paddle_device()
    if _PADDLE_STRUCTURE is not None and _PADDLE_STRUCTURE_INIT_DEVICE == device:
        return _PADDLE_STRUCTURE
    if _PADDLE_STRUCTURE_INIT_ERROR is not None and _PADDLE_STRUCTURE_INIT_DEVICE == device:
        return None
    if not _paddle_layout_ready():
        _PADDLE_STRUCTURE_INIT_DEVICE = device
        _PADDLE_STRUCTURE_INIT_ERROR = "布局模型目录不存在或缺少模型文件"
        return None
    with _PADDLE_STRUCTURE_LOCK:
        if _PADDLE_STRUCTURE is not None and _PADDLE_STRUCTURE_INIT_DEVICE == device:
            return _PADDLE_STRUCTURE
        try:
            structure = _init_paddle_structure(device)
            _PADDLE_STRUCTURE = structure
            _PADDLE_STRUCTURE_INIT_DEVICE = device
            _PADDLE_STRUCTURE_INIT_ERROR = None
            return structure
        except Exception as exc:  # 初始化失败时回退普通 OCR，不阻塞用户
            _PADDLE_STRUCTURE_INIT_DEVICE = device
            if device == "gpu":
                os.environ["HABIT_OCR_DEVICE"] = "cpu"
                _PADDLE_STRUCTURE = None
                _PADDLE_STRUCTURE_INIT_DEVICE = None
                _PADDLE_STRUCTURE_INIT_ERROR = None
                try:
                    structure = _init_paddle_structure("cpu")
                    _PADDLE_STRUCTURE = structure
                    _PADDLE_STRUCTURE_INIT_DEVICE = "cpu"
                    return structure
                except Exception as cpu_exc:
                    _PADDLE_STRUCTURE_INIT_DEVICE = "cpu"
                    _PADDLE_STRUCTURE_INIT_ERROR = "布局识别初始化失败：{}".format(cpu_exc)
                    return None
            _PADDLE_STRUCTURE_INIT_ERROR = str(exc)
            return None


def _block_attr(item, name, default=None):
    """从 PP-StructureV3 布局块（dict 或对象）中取字段。"""
    try:
        if isinstance(item, dict):
            return item.get(name, default)
        return getattr(item, name, default)
    except Exception:
        return default


def _page_structured_records(page):
    """把一页 PP-StructureV3 的解析块整理成按阅读顺序排列的记录。"""
    records = []
    for item in page.get("parsing_res_list") or []:
        label = str(_block_attr(item, "label") or "").strip().lower()
        content = str(_block_attr(item, "content") or "").strip()
        if not content:
            continue
        order = _block_attr(item, "order_index")
        if order is None:
            order = _block_attr(item, "index")
        records.append({
            "label": label,
            "content": content,
            "bbox": _block_attr(item, "bbox") or [],
            "order": int(order) if order is not None else len(records),
        })
    records.sort(key=lambda r: r["order"])
    return records


def ocr_structured_blocks(path):
    """用 PP-StructureV3 识别页面布局，返回按顺序的 [{label, content, bbox, order}]。

    保留标题（paragraph_title/doc_title 等）与正文的原始结构，供知识库按标题段落切分。
    模型缺失、初始化失败或识别异常时返回 None，由调用方回退普通 OCR。
    """
    if os.environ.get("HABIT_OCR_ENGINE", "paddle").lower() == "winrt":
        return None
    structure = _get_paddle_structure()
    if structure is None:
        return None
    try:
        pages = structure.predict(path)
        records = []
        for page in pages or []:
            records.extend(_page_structured_records(page))
        return records or None
    except Exception:
        return None

def _poly_to_xy(poly, fallback_box):
    """从识别框取左上角坐标：优先用四边形各点最小值，失败时用整框坐标。"""
    try:
        pts = list(poly)
        xs = [float(p[0]) for p in pts]
        ys = [float(p[1]) for p in pts]
        return int(min(xs)), int(min(ys))
    except Exception:
        try:
            box = list(fallback_box)
            return int(box[0]), int(box[1])
        except Exception:
            return 0, 0


def _run_paddle_ocr(path, timeout=20):
    """运行 PaddleOCR，返回 [(x, y, text)]；失败返回 None。"""
    engine = _get_paddle_ocr()
    if engine is None:
        return None
    try:
        results = engine.predict(path)
        out = []
        for page in results:
            texts = page.get("rec_texts") or []
            polys = page.get("rec_polys") or []
            boxes = page.get("rec_boxes") or []
            for i, text in enumerate(texts):
                if not text or not str(text).strip():
                    continue
                poly = polys[i] if i < len(polys) else None
                box = boxes[i] if i < len(boxes) else None
                x, y = _poly_to_xy(poly, box)
                out.append((x, y, str(text)))
        return out or None
    except Exception:
        return None


def _ocr_engine_candidates(keep_marks=False):
    """返回识别引擎候选列表：Paddle 优先，WinRT 兜底。"""
    engines = []
    if os.environ.get("HABIT_OCR_ENGINE", "paddle").lower() != "winrt":
        engines.append(_run_paddle_ocr)
    engines.append(_run_ocr)
    return engines


def ocr_image_lines(path, timeout=20, keep_marks=False):
    """识别单张图片（先预处理提升准确率），返回按行清理后的文字列表；失败返回 None。

    keep_marks=True 时保留红笔/手写标注（不清理颜色）。
    """
    pre = None
    try:
        try:
            pre = preprocess_for_ocr(path, keep_marks=keep_marks)
        except Exception:
            pre = None
        # Paddle 直接识别原图（保留红笔/彩色信息），不重复跑预处理图；
        # WinRT 仍按原顺序试预处理图和原图。
        if os.environ.get("HABIT_OCR_ENGINE", "paddle").lower() != "winrt":
            lines = _run_paddle_ocr(path, timeout=timeout)
            if lines:
                return [cleanup_cjk_spaces(t).strip() for _, _, t in lines if t.strip()]
        for candidate in (pre, path):
            if not candidate:
                continue
            lines = _run_ocr(candidate, timeout=timeout)
            if lines:
                return [cleanup_cjk_spaces(t).strip() for _, _, t in lines if t.strip()]
        return None
    finally:
        _remove_temp_file(pre)


def ocr_lines_with_y(path, timeout=20, keep_marks=False):
    """识别图片，返回 [(x, y, text)]，y 为行在原图上的纵向坐标（用于按题切分）。"""
    pre = None
    try:
        try:
            pre = preprocess_for_ocr(path, keep_marks=keep_marks)
        except Exception:
            pre = None
        if os.environ.get("HABIT_OCR_ENGINE", "paddle").lower() != "winrt":
            lines = _run_paddle_ocr(path, timeout=timeout)
            if lines:
                out = []
                for x, y, t in lines:
                    t2 = cleanup_cjk_spaces(t).strip()
                    if t2:
                        out.append((int(x), int(y), t2))
                return out
        for candidate in (pre, path):
            if not candidate:
                continue
            lines = _run_ocr(candidate, timeout=timeout)
            if lines:
                out = []
                for x, y, t in lines:
                    t2 = cleanup_cjk_spaces(t).strip()
                    if t2:
                        out.append((int(x), int(y), t2))
                return out
        return None
    finally:
        _remove_temp_file(pre)


def ocr_image(path, timeout=20):
    """识别单张图片文字；成功返回文本（已清理汉字空格），失败返回 None。"""
    lines = ocr_image_lines(path, timeout=timeout)
    if lines is None:
        return None
    return "\n".join(lines)


_QNUM_RE = re.compile(r"^(\d{1,3})(?:[.、．）),，]\s*|\s+|(?=[\u4e00-\u9fffA-Za-z（(]))(.*)$")
_OPT_RE = re.compile(r"^([A-Ha-h])\s*[.、．）)]\s*(.*)$")
_ANNOT_RE = re.compile(r"^[（(]\s*(\d{4}|\d{1,2}\s*年)")


def _normalize_width(text):
    """全角字母数字转半角。"""
    out = []
    for ch in text or "":
        o = ord(ch)
        if o == 0x3000:
            out.append(" ")
        elif 0xFF01 <= o <= 0xFF5E:
            out.append(chr(o - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def parse_ocr_questions(lines):
    """把 OCR 识别行解析成一道道题。

    规则：
    - 以 "1." / "3、" / "12．" 等开头的行 → 新题开始（题干）
    - 以 "A." / "B、" 等开头的行 → 当前题的选项
    - 其他行 → 追加到当前题题干
    返回 [{num, stem, options:[str,...]}]，空题会被过滤。
    """
    questions = []
    cur = None
    for raw in lines or []:
        line = _normalize_width(raw or "").strip()
        if not line:
            continue
        m = _QNUM_RE.match(line)
        if m:
            cur = {"num": int(m.group(1)), "stem": m.group(2).strip(), "options": []}
            questions.append(cur)
            continue
        if _ANNOT_RE.match(line):
            # 以出处标注（如（2017 天津））开头的行视为一道新题
            cur = {"num": None, "stem": line, "options": []}
            questions.append(cur)
            continue
        mo = _OPT_RE.match(line)
        if mo:
            if cur is None:
                cur = {"num": None, "stem": "", "options": []}
                questions.append(cur)
            first = mo.group(1).upper()
            rest = mo.group(2).strip()
            # 同一行可能含多个选项：A. xx B. yy C. zz
            pieces = re.split(r"\s+(?=[A-H][.、．）)]\s)", rest)
            for i, piece in enumerate(pieces):
                piece = piece.strip()
                if not piece:
                    continue
                if i == 0:
                    cur["options"].append("{}. {}".format(first, piece))
                else:
                    m2 = re.match(r"^([A-H])\s*[.、．）)]\s*(.*)$", piece)
                    if m2:
                        cur["options"].append("{}. {}".format(m2.group(1).upper(), m2.group(2).strip()))
                    else:
                        cur["options"].append(piece)
            continue
        if cur is None:
            cur = {"num": None, "stem": "", "options": []}
            questions.append(cur)
        # 题干已存在时，跳过过短的独立行（多为批注/圈画噪声，如“错题”）
        if cur["stem"] and len(line) < 3:
            continue
        cur["stem"] = (cur["stem"] + " " + line).strip()
    return [q for q in questions if q["stem"] or q["options"]]


_TEXT_KEYWORDS = [
    "的", "了", "是", "在", "从", "与", "之", "使", "呈现", "规律",
    "选择", "填入", "问号", "四个", "选项", "图形", "一定", "能够",
    "这段", "说明", "意在", "下列", "正确", "错误", "根据",
]


def _is_text_line(t):
    """判断 OCR 行是否像正常文字（排除图形区被误读的乱码短行）。"""
    t = t or ""
    return any(k in t for k in _TEXT_KEYWORDS)


def split_figure_stems(lines):
    """从 OCR 文本行中按题干切分图形推理题（过滤图形区乱码行）。

    返回 [{num, stem}]；找不到题干返回 None。
    """
    qnum_re = re.compile(r"^(\d{1,3})\s*[.、，．]")
    stem_re = re.compile(r"(从所给的四个选项|两套图形)")
    starts = []
    for i, t in enumerate(lines):
        if qnum_re.match(t) or stem_re.search(t):
            starts.append(i)
    if not starts:
        return None
    results = []
    for k, idx in enumerate(starts):
        nxt = starts[k + 1] if k + 1 < len(starts) else len(lines)
        stem_lines = []
        for t in lines[idx:nxt]:
            if _is_text_line(t):
                stem_lines.append(t)
            elif len(stem_lines) >= 1:
                break  # 遇到图形区乱码行即结束本题干
        stem = "\n".join(stem_lines).strip() or (lines[idx] or "").strip()
        m = qnum_re.match(lines[idx])
        num = int(m.group(1)) if m else k + 1
        results.append({"num": num, "stem": stem, "options": []})
    return results


def normalize_ocr_text(text):
    """统一 OCR 文本的标点与空格：中文冒号/逗号/问号/叹号统一为全角，
    选项字母后的全角点转半角（A．→ A.），合并多余空格，清理行首尾。
    """
    out = []
    for raw in (text or "").splitlines():
        s = raw.strip()
        s = s.replace(":", "：").replace(",", "，").replace(";", "；")
        s = s.replace("?", "？").replace("!", "！")
        s = re.sub(r"([A-Ha-h])．", r"\1.", s)
        s = re.sub(r"\s+", " ", s).strip()
        if s:
            out.append(s)
    return "\n".join(out)


def _clean_leading_junk(text):
    """去掉行首被 OCR 误读的序号/字母等非中文前缀（保留中文或左括号起头）。"""
    m = re.search(r"[\u4e00-\u9fff（(]", text or "")
    if m:
        return text[m.start():].strip()
    return (text or "").strip()


def _strip_option_letter(text):
    """安全去除选项行首被 OCR 误读的字母/符号前缀。

    只处理确定性的：行首非中文符号（如 "& "、"0。"、"A. "），
    或 单个中文字符 + 中文标点（如 "人."、"步,"）；不处理带空格的
    （避免误删真实内容，如 "港亠 i"）。
    """
    s = (text or "").strip()
    changed = True
    while changed:
        changed = False
        m = re.match(r"^[^\u4e00-\u9fff]+", s)  # 行首非中文符号
        if m:
            s = s[m.end():].strip()
            changed = True
            continue
        m2 = re.match(r"^([\u4e00-\u9fff])(?=[。、，,.:：)）])", s)  # 单字+标点
        if m2:
            s = s[m2.end():].strip()
            changed = True
    return s


def _clean_stem(line):
    """清理题干行：去除行首误读的题号/年份前缀；若残留「省份）」则移到末尾作来源。"""
    s = _clean_leading_junk(line)
    m = re.match(r"^([\u4e00-\u9fff]{2,4})[）)]", s)
    if m and not (s.startswith("（") or s.startswith("(")):
        s = s[m.end():].strip()
        if s:
            s = s + "（来源：" + m.group(1) + "）"
    return s


def reconstruct_page(lines):
    """针对规整题目页（题号 + （年份·省份）+ 题干术语，后跟 A/B/C/D 选项）重构。

    OCR 常把题号（1./2.）与选项字母（A/B/C/D）误读，但术语内容基本可读。
    本函数忽略序号/字母的误读，按出现顺序把页面重组为 N 道题：
    返回 [{num, stem, options:[str,...]}]；结构不规整返回 None。
    """
    year_q = re.compile(r"[（(]\s*\d{2,4}\s*[·．.、]")
    questions = []
    cur = None
    for raw in lines or []:
        line = _normalize_width((raw or "").strip())
        if not line:
            continue
        terms = [t.strip() for t in re.split(r"[：:]", line) if t.strip()]
        if len(terms) < 2:
            continue  # 跳过碎片/批注行
        if year_q.search(line) or cur is None or len(cur["options"]) >= 4:
            if cur is not None and (cur["stem"] or cur["options"]):
                questions.append(cur)
            cur = {"num": len(questions) + 1, "stem": line, "options": []}
        else:
            terms2 = [_strip_option_letter(terms[0])] + terms[1:]
            cleaned = "：".join(terms2).strip("： ")
            cur["options"].append("{}. {}".format(chr(65 + len(cur["options"])), cleaned))
    if cur is not None and (cur["stem"] or cur["options"]):
        questions.append(cur)
    # 结构校验：至少存在一道含 ≥2 选项的题（跨页时末题可能不完整，予以保留）
    if not questions or not any(len(q["options"]) >= 2 for q in questions):
        return None
    for q in questions:
        q["stem"] = _clean_stem(q["stem"])
    return questions


def format_questions_text(questions):
    """把题目列表格式化为美观文本（每道题题干+选项，题与题之间空一行）。"""
    blocks = []
    for q in questions:
        parts = []
        prefix = ("{}. ".format(q["num"])) if q["num"] else ""
        parts.append(prefix + (q["stem"] or "（题干未识别）"))
        parts.extend(q["options"])
        blocks.append("\n".join(parts))
    return "\n\n".join(blocks)
