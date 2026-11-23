"""Page plans contain no rendered images. All coordinates use displayed PDF points."""

from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
import os
import shutil
import tempfile
import pymupdf as pdf

ASSETS = Path(__file__).resolve().parent / "assets"


@dataclass(frozen=True)
class Leaf:
    path: str = ""
    index: int = 0
    password: str = field(default="", repr=False)
    turn: int = 0
    crop: tuple | None = None  # absolute unrotated CropBox
    marks: tuple = ()  # coordinates relative to original unrotated CropBox


def open_pdf(path, password=""):
    doc = pdf.open(path)
    if not doc.is_pdf or (doc.needs_pass and not doc.authenticate(password)):
        locked = doc.needs_pass
        doc.close()
        if locked:
            raise PermissionError("パスワードが必要です。")
        raise ValueError("PDFファイルを指定してください。")
    return doc


def pages(spec, total):
    result = []
    seen = set()
    for item in spec.split(","):
        parts = item.strip().split("-")
        if len(parts) > 2 or any(not p.strip().isdecimal() for p in parts):
            raise ValueError("ページは 1-5, 8 の形式で指定してください。")
        first, last = int(parts[0]), int(parts[-1])
        if not 1 <= first <= last <= total:
            raise ValueError("ページ範囲を確認してください。")
        for i in range(first - 1, last):
            if i in seen:
                raise ValueError("ページ指定が重複しています。")
            seen.add(i)
            result.append(i)
    return result


def decorate(page, leaf):
    for kind, coords, value, size, color in leaf.marks:
        box = pdf.Rect(coords)
        if kind == "文字":
            page.insert_text(
                (box.x0, box.y0 + size),
                value,
                fontname="japan",
                fontsize=size,
                color=color,
            )
        elif kind == "画像":
            page.insert_image(box, stream=value)
        elif kind == "メモ":
            page.add_text_annot(box.tl, value).update()
        elif kind in ("ハイライト", "下線"):
            annot = (
                page.add_highlight_annot(box)
                if kind == "ハイライト"
                else page.add_underline_annot(box)
            )
            annot.update()
        elif kind == "四角形":
            page.draw_rect(box, color=color, width=2)
        else:
            page.draw_line(box.tl, box.br, color=color, width=2)
            if kind == "矢印":
                import math

                angle = math.atan2(box.height, box.width)
                for offset in (-0.45, 0.45):
                    point = (
                        box.x1 - 10 * math.cos(angle + offset),
                        box.y1 - 10 * math.sin(angle + offset),
                    )
                    page.draw_line(box.br, point, color=color, width=2)
    if leaf.crop:
        page.set_cropbox(pdf.Rect(leaf.crop))
    page.set_rotation((page.rotation + leaf.turn) % 360)


class Builder:
    def __init__(self):
        self.stack = ExitStack()
        self.inputs = {}
        self.doc = self.stack.enter_context(pdf.open())

    def add(self, leaf):
        if leaf.path:
            key = (leaf.path, leaf.password)
            if key not in self.inputs:
                self.inputs[key] = self.stack.enter_context(open_pdf(*key))
            self.doc.insert_pdf(
                self.inputs[key], from_page=leaf.index, to_page=leaf.index, widgets=True
            )
        else:
            self.doc.new_page()
        page = self.doc[-1]
        decorate(page, leaf)
        return page

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.stack.close()


def crop_coords(page, rect):
    local = (pdf.Rect(rect) & page.rect) * page.derotation_matrix
    base = page.cropbox_position
    return tuple(local + (base.x, base.y, base.x, base.y))


def render(leaf, scale, rect=None):
    with Builder() as build:
        page = build.add(leaf)
        pix = page.get_pixmap(matrix=pdf.Matrix(scale, scale), clip=rect, alpha=False)
        return pix.tobytes("png"), tuple(page.rect)


def recognize(leaf, rect, lang):
    with Builder() as build:
        page = build.add(leaf)
        text = page.get_textbox(pdf.Rect(rect) * page.derotation_matrix).strip()
        if text:
            return text
        pix = page.get_pixmap(dpi=300, clip=pdf.Rect(rect), alpha=False)
        blob = pix.pdfocr_tobytes(language=lang, tessdata=str(ASSETS / "tessdata"))
        with pdf.open(stream=blob, filetype="pdf") as ocr:
            return ocr[0].get_text().strip()


def write_pdf(leaves, target, compression=None, progress=lambda *_: None):
    target = Path(target)
    if any(
        leaf.path and Path(leaf.path).resolve() == target.resolve() for leaf in leaves
    ):
        raise ValueError("元ファイルを保護するため、別の保存先を指定してください。")
    raster = compression and len(compression) == 3 and compression[2] == "raster"
    with Builder() as build:
        for n, leaf in enumerate(leaves, 1):
            if raster:
                dpi, quality, _ = compression
                with Builder() as image_doc:
                    page = image_doc.add(leaf)
                    pix = page.get_pixmap(dpi=dpi, alpha=False)
                    image = pix.tobytes("jpeg", jpg_quality=quality)
                    target_page = build.doc.new_page(
                        width=page.rect.width, height=page.rect.height
                    )
                    target_page.insert_image(target_page.rect, stream=image)
            else:
                build.add(leaf)
            if n == len(leaves) or n % 12 == 0:
                progress(n, len(leaves))
        if compression and compression[0] and not raster:
            dpi, quality = compression
            build.doc.rewrite_images(
                dpi_threshold=dpi + 1, dpi_target=dpi, quality=quality
            )
        build.doc.save(
            target, garbage=4 if compression else 2, deflate=True, use_objstms=1
        )


def safe_save(leaves, dest, compression=None, progress=lambda *_: None):
    dest = Path(dest)
    if any(x.path and Path(x.path).resolve() == dest.resolve() for x in leaves):
        raise ValueError("元のPDFとは別のファイル名を指定してください。")
    if shutil.disk_usage(dest.parent).free < 4096:
        raise OSError("ディスクの空き容量が不足しています。")
    fd, name = tempfile.mkstemp(dir=dest.parent, suffix=".part")
    os.close(fd)
    try:
        write_pdf(leaves, name, compression, progress)
        with pdf.open(name) as doc:
            if len(doc) != len(leaves):
                raise ValueError("保存ページ数が一致しません。")
        os.replace(name, dest)
    finally:
        Path(name).unlink(missing_ok=True)
