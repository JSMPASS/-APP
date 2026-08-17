"""图形处理：图形图片去背景、图形推理页按题号切分。"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path


def make_transparent_bg(src_path, out_path=None, luminance_threshold=230):
    """把浅色/白色背景设为透明，保留图形内容，输出 PNG。返回输出路径。"""
    import numpy as np
    from PIL import Image
    img = Image.open(src_path).convert("RGBA")
    arr = np.asarray(img).astype(np.int16)
    r, g, b, a = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    bg = lum > luminance_threshold
    a[bg] = 0
    out_arr = np.dstack([r, g, b, a]).astype(np.uint8)
    out_img = Image.fromarray(out_arr, "RGBA")
    if out_path is None:
        out_path = str(Path(tempfile.gettempdir()) / "habit_figure_bg.png")
    out_img.save(out_path, "PNG")
    return out_path


def split_figure_page(image_path, keep_marks=False, fig_min_h=60):
    """图形推理页按题号切分（不依赖 OCR 行坐标）。

    题干按 OCR 文本行顺序切分（过滤图形区被误读的短行）；
    图形区用「行投影」找高带，并按题号顺序分配给各题，整块提取为透明背景图。
    返回 [{num, stem, figure_path}]；无法识别返回 None。
    """
    import numpy as np
    from PIL import Image

    from habit_checkin.services.ocr import ocr_image_lines

    img = Image.open(image_path)
    w, h = img.size
    lines = ocr_image_lines(image_path, keep_marks=keep_marks) or []
    qnum_re = re.compile(r"^(\d{1,3})\s*[.、，．]")
    stem_re = re.compile(r"(从所给的四个选项|填入问号处|呈现.*规律性|两套图形)")
    starts = [t for t in lines if qnum_re.match(t)]
    if not starts:
        starts = [t for t in lines if stem_re.search(t)]
    if not starts:
        return None

    # 行投影找高带（图形区）
    arr = np.asarray(img.convert("L"))
    dark = arr < 150
    row_density = dark.sum(axis=1)
    bands = []
    in_band = False
    for y in range(h):
        if row_density[y] > 3 and not in_band:
            start_y = y
            in_band = True
        elif row_density[y] <= 3 and in_band:
            bands.append((start_y, y))
            in_band = False
    if in_band:
        bands.append((start_y, h))
    fig_bands = [(a, b) for a, b in bands if b - a >= fig_min_h]

    results = []
    start_indices = [i for i, t in enumerate(lines) if t in starts]
    for i, idx in enumerate(start_indices):
        nxt = next((j for j in start_indices if j > idx), len(lines))
        stem_lines = [t for t in lines[idx:nxt] if len(t) >= 4]
        stem = "\n".join(stem_lines)
        figure_path = None
        if i < len(fig_bands):
            a, b = fig_bands[i]
            if b - a > 20:
                fig_crop = img.crop((0, a, w, b))
                if int((np.asarray(fig_crop.convert("L")) < 150).sum()) > 50:
                    tmp = Path(tempfile.gettempdir()) / "habit_qfig.png"
                    fig_crop.save(tmp, "PNG")
                    figure_path = make_transparent_bg(str(tmp))
        m = qnum_re.match(starts[i])
        num = int(m.group(1)) if m else i + 1
        results.append({"num": num, "stem": stem, "figure_path": figure_path})
    return results
