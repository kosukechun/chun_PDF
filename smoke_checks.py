"""Exercise the same subprocess and staging paths as the Windows UI."""

import tempfile
import time
from pathlib import Path
from tkinterdnd2 import TkinterDnD
import engine as e


def wait(gui, predicate):
    limit = time.monotonic() + 40
    while not predicate() and time.monotonic() < limit:
        gui.root.update()
        time.sleep(0.01)
    assert predicate(), gui.status.get()


def run():
    from app import App
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as folder:
        root = TkinterDnD.Tk()
        root.withdraw()
        gui = App(root)
        try:
            path = Path(folder) / "日本語 原本.pdf"
            data = (e.ASSETS / "ocr-sample.png").read_bytes()
            with e.pdf.open() as scanned:
                page = scanned.new_page(width=288, height=72)
                page.insert_image(page.rect, stream=data)
                scanned.save(path)
            gui.load([path])
            wait(gui, lambda: gui.photo is not None)
            result = []
            with patch("tkinter.messagebox.showerror", side_effect=AssertionError):
                gui.launch(
                    "ocr", (gui.items[0], (0, 0, 288, 72), "jpn+eng"), result.append
                )
                wait(gui, lambda: gui.job is None)
                assert "文書" in "".join(result[0].split()), repr(result)
                gui.edit("回転")
                wait(gui, lambda: gui.photo is not None)
                assert gui.dims.width == 72
                gui.history(False)
                wait(gui, lambda: gui.photo is not None)
                gui.rect = (10, 10, 140, 66)
                gui.apply_crop("現在")
                wait(gui, lambda: gui.job is None and gui.photo is not None)
                assert gui.dims.width == 130
                target = Path(folder) / "編集済み.pdf"
                gui.export([(gui.items, target, None)], True)
                wait(gui, lambda: gui.job is None)
                with e.open_pdf(target) as saved:
                    assert saved[0].rect.width == 130
                original = target.read_bytes()
                gui.export([([e.Leaf()] * 1500, target, None)], False)
                gui.cancel()
                assert target.read_bytes() == original and not list(
                    target.parent.glob("*.part")
                )
        finally:
            gui.dirty = False
            gui.quit()
