"""离线 OCR：调用 Windows 自带 WinRT OCR（优先简体中文），识别图片中的文字。

实现：把 PowerShell 脚本写入临时文件，用 powershell -ExecutionPolicy Bypass -File 调用。
注意不要使用 -WindowStyle Hidden（在该运行环境下会导致进程异常退出）。
OCR 结果仅作预填，由用户确认/编辑。
"""
from __future__ import annotations

import os
import re
import tempfile

from habit_checkin.services.powershell import run_powershell_script

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
