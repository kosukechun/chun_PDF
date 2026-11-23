import io
import multiprocessing as mp
import os
from pathlib import Path
import queue
import sys
import tempfile
import time
import tkinter as tk
from tkinter import (
    ttk,
    filedialog as files,
    messagebox as msg,
    simpledialog as ask,
    colorchooser,
)
from dataclasses import replace
from PIL import Image, ImageTk
from tray import Tray
from preview import Renderer
from tkinterdnd2 import TkinterDnD, DND_FILES
import engine as e
import windows as win


def worker(channel, op, payload):
    try:
        if op == "ocr":
            result = e.recognize(*payload)
        elif op == "crop":
            current, ids, rect = payload
            result = []
            for n, i in enumerate(ids, 1):
                with e.Builder() as b:
                    p = b.add(current[i])
                    clip = e.pdf.Rect(rect) & p.rect
                    if clip.is_empty:
                        raise ValueError(
                            f"{i + 1}ページ目で選択範囲がページ外になります。"
                        )
                    result.append((i, e.crop_coords(p, clip)))
                if n % 12 == 0:
                    channel.send(("progress", n / len(ids)))
        elif op == "image":
            result = e.render(*payload)[0]
        else:
            for k, (leaves, stage, comp) in enumerate(payload):

                def progress(n, total):
                    channel.send(("progress", (k + n / total) / len(payload)))

                e.write_pdf(leaves, stage, comp, progress)
                with e.pdf.open(stage) as check:
                    if len(check) != len(leaves):
                        raise ValueError("保存内容を検証できません。")
            result = None
        channel.send(("ok", result))
    except Exception as exc:
        channel.send(("error", str(exc)))
    finally:
        channel.close()


class App:
    def __init__(self, root, tray=False):
        self.root = root
        root.title(win.TITLE)
        root.geometry("1150x790")
        root.minsize(760, 520)
        self.items = []
        self.past, self.future = [], []
        self.dirty = False
        self.active = 0
        self.closed = False
        self.zoom = 1.0
        self.rect = None
        self.job = None
        self.thumb = {}
        self.photo = None
        self.prefs = win.prefs()
        self.mode = tk.StringVar(value="範囲選択")
        self.dpi = tk.IntVar(value=self.prefs.get("dpi", 300))
        self.lang = tk.StringVar(value=self.prefs.get("lang", "jpn+eng"))
        self.status = tk.StringVar(value="PDFを開くか、ここにドロップしてください。")
        self.info = tk.StringVar()
        self.events = queue.Queue()
        self.stages = []
        self.renderer = Renderer()
        self.generation = 0
        self.displayed = None
        self.last_view = None
        self.style = ttk.Style(root)
        self.style.theme_use("clam")
        self.layout()
        self.theme()
        self.icon_image = Image.open(e.ASSETS / "app_icon.png").convert("RGBA")
        self.tk_icon = ImageTk.PhotoImage(self.icon_image)
        root.iconphoto(True, self.tk_icon)
        commands = [
            ("chun PDFを開く", self.show),
            ("PDFを開く", self.open),
            ("PDFを結合", lambda: self.open(True)),
            ("PDFを圧縮", self.compress),
            ("設定", self.settings),
            ("終了", self.quit),
        ]
        self.tray = Tray(e.ASSETS / "app.ico", commands, self.events.put)
        self.poll_events()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.drop_target_register(DND_FILES)
        root.dnd_bind("<<Drop>>", lambda ev: self.load(root.tk.splitlist(ev.data)))
        if tray and not self.tray.error:
            root.withdraw()

    def poll_events(self):
        while not self.events.empty():
            fn = self.events.get()
            self.show()
            fn()
            if self.closed:
                return
        if win.reactivate():
            self.show()
        if self.root.winfo_exists():
            self.root.after(150, self.poll_events)

    def show(self):
        self.root.deiconify()
        self.root.lift()

    def theme(self):
        dark = self.prefs.get("dark", False)
        bg, fg = ("#26313a", "#f3f6f7") if dark else ("#f2f5f4", "#192d32")
        self.style.configure(
            ".", background=bg, foreground=fg, font=("Yu Gothic UI", 10)
        )
        self.style.configure(
            "Treeview", fieldbackground=bg, background=bg, foreground=fg, rowheight=67
        )
        self.style.map(
            "Treeview",
            background=[("selected", "#236e70")],
            foreground=[("selected", "white")],
        )
        self.style.map("TButton", foreground=[("active", "#14282b")])
        self.root.configure(bg=bg)
        self.canvas.configure(bg="#19262b" if dark else "#cdd5d5")

    def layout(self):
        root = self.root
        menu = tk.Menu(root)
        root.config(menu=menu)

        def group(title, commands):
            m = tk.Menu(menu, tearoff=False)
            menu.add_cascade(label=title, menu=m)
            for label, cmd in commands:
                m.add_command(label=label, command=cmd)
            return m

        group(
            "ファイル",
            [
                ("PDFを追加", self.open),
                ("範囲を指定して結合", lambda: self.open(True)),
                ("名前を付けて保存", self.save),
                ("作業をクリア", self.clear),
                ("設定", self.settings),
                ("終了", self.quit),
            ],
        )
        group(
            "ページ",
            [
                (label, lambda k=label: self.edit(k))
                for label in ["回転", "複製", "削除", "空白追加", "上へ", "下へ"]
            ]
            + [
                ("選択ページを保存", lambda: self.save(self.selected())),
                ("範囲抽出・分割", self.split),
                ("別PDFにコピー", lambda: self.transfer(False)),
                ("別PDFに移動", lambda: self.transfer(True)),
                ("元に戻す", lambda: self.history(False)),
                ("やり直す", lambda: self.history(True)),
            ],
        )
        group(
            "編集",
            [
                (label, lambda k=label: self.mark(k))
                for label in [
                    "文字",
                    "四角形",
                    "線",
                    "矢印",
                    "ハイライト",
                    "下線",
                    "メモ",
                    "画像",
                ]
            ]
            + [("直前の追加要素を選択枠へ移動・サイズ変更", self.reposition)],
        )
        top = ttk.Frame(root, padding=6)
        top.pack(fill="x")
        for name, cmd in [
            ("開く", self.open),
            ("保存", self.save),
            ("結合", lambda: self.open(True)),
            ("分割", self.split),
            ("圧縮", self.compress),
            ("トリミング", self.crop_menu),
            ("画像コピー", lambda: self.setmode("画像コピー")),
            ("文字スキャン", lambda: self.setmode("文字スキャン")),
            ("設定", self.settings),
        ]:
            ttk.Button(top, text=name, command=cmd, width=10).pack(side="left", padx=2)
        pane = ttk.Panedwindow(root, orient="horizontal")
        pane.pack(fill="both", expand=True)
        side = ttk.Frame(pane)
        pane.add(side, weight=1)
        ttk.Label(side, text="ページ", padding=6).pack(anchor="w")
        self.tree = ttk.Treeview(side, show="tree", selectmode="extended", height=6)
        self.tree.column("#0", width=150, minwidth=110)
        bar = ttk.Scrollbar(side, command=self.tree.yview)
        bar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.choose)
        self.tree.bind(
            "<ButtonPress-1>",
            lambda ev: setattr(self, "dragrow", self.tree.identify_row(ev.y)),
        )
        self.tree.bind("<ButtonRelease-1>", self.reorder)
        center = ttk.Frame(pane)
        pane.add(center, weight=5)
        self.canvas = tk.Canvas(center, highlightthickness=0, width=540)
        v = ttk.Scrollbar(center, orient="vertical", command=self.canvas.yview)
        h = ttk.Scrollbar(center, orient="horizontal", command=self.canvas.xview)
        v.pack(side="right", fill="y")
        h.pack(side="bottom", fill="x")
        self.canvas.configure(xscrollcommand=h.set, yscrollcommand=v.set)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self.down)
        self.canvas.bind("<B1-Motion>", self.motion)
        self.canvas.bind("<ButtonRelease-1>", self.up)
        self.canvas.bind(
            "<MouseWheel>",
            lambda ev: self.canvas.yview_scroll(-int(ev.delta / 120) * 3, "units"),
        )
        self.canvas.bind(
            "<Control-MouseWheel>",
            lambda ev: self.scale(1.2 if ev.delta > 0 else 1 / 1.2),
        )
        self.context = tk.Menu(root, tearoff=False)
        for label, cmd in [
            ("画像をコピー", self.image),
            ("PNG / JPEGを保存", lambda: self.image(True)),
            ("文字を抽出", self.ocr),
            ("トリミング", self.crop_menu),
        ]:
            self.context.add_command(label=label, command=cmd)
        self.canvas.bind(
            "<Button-3>", lambda ev: self.context.tk_popup(ev.x_root, ev.y_root)
        )
        right = ttk.Frame(pane, padding=10)
        pane.add(right, weight=1)
        ttk.Label(right, textvariable=self.info, wraplength=164).pack(anchor="w")
        ttk.Separator(right).pack(fill="x", pady=10)
        ttk.Label(right, textvariable=self.mode).pack(anchor="w")
        for name, cmd in [
            ("範囲選択・位置調整", lambda: self.setmode("範囲選択")),
            ("選択範囲を画像保存", lambda: self.image(True)),
            ("選択ページを回転", lambda: self.edit("回転")),
            ("トリミング解除", lambda: self.apply_crop("解除")),
            ("前のページ", lambda: self.goto(self.active - 1)),
            ("次のページ", lambda: self.goto(self.active + 1)),
            ("拡大 ＋", lambda: self.scale(1.2)),
            ("縮小 －", lambda: self.scale(1 / 1.2)),
        ]:
            ttk.Button(right, text=name, command=cmd).pack(fill="x", pady=2)
        foot = ttk.Frame(root, padding=5)
        foot.pack(fill="x")
        ttk.Label(foot, textvariable=self.status).pack(
            side="left", fill="x", expand=True
        )
        self.bar = ttk.Progressbar(foot, length=100)
        self.bar.pack(side="left")
        self.cancel_btn = ttk.Button(
            foot, text="キャンセル", command=self.cancel, state="disabled"
        )
        self.cancel_btn.pack(side="left")
        for key, fn in [
            ("Control-o", self.open),
            ("Control-s", self.save),
            ("Control-z", lambda: self.history(False)),
            ("Control-y", lambda: self.history(True)),
            ("Delete", lambda: self.edit("削除")),
            ("F6", lambda: self.setmode("画像コピー")),
            ("F7", lambda: self.setmode("文字スキャン")),
        ]:
            root.bind("<" + key + ">", lambda ev, f=fn: f())
        root.after(200, self.thumbnails)

    def load(self, paths, ranges=False):
        added = []
        for name in paths:
            try:
                name = str(Path(name).resolve())
                pw = ""
                while True:
                    try:
                        doc = e.open_pdf(name, pw)
                        break
                    except PermissionError:
                        pw = ask.askstring(
                            "PDFを開く", Path(name).name + " のパスワード", show="*"
                        )
                        if pw is None:
                            return
                with doc:
                    ids = range(len(doc))
                    if ranges:
                        spec = ask.askstring(
                            "結合するページ",
                            f"{Path(name).name}（{len(doc)}ページ）",
                            initialvalue=f"1-{len(doc)}",
                        )
                        if spec is None:
                            return
                        ids = e.pages(spec, len(doc))
                    added.extend(e.Leaf(name, i, pw) for i in ids)
            except Exception as exc:
                msg.showerror("PDFを開く", str(exc))
                return
        if added:
            self.change(self.items + added, len(self.items))

    def open(self, ranges=False):
        self.load(files.askopenfilenames(filetypes=[("PDF", "*.pdf")]), ranges)

    def selected(self):
        return sorted(map(int, self.tree.selection()))

    def change(self, new, focus):
        self.past.append((self.items, self.active))
        self.future.clear()
        self.items = new
        self.dirty = True
        self.refresh(focus)

    def history(self, redo):
        src, dst = (self.future, self.past) if redo else (self.past, self.future)
        if src:
            dst.append((self.items, self.active))
            self.items, at = src.pop()
            self.dirty = True
            self.refresh(at)

    def clear(self):
        if self.items and msg.askyesno(
            "作業をクリア", "すべてのページを作業一覧から外しますか？"
        ):
            self.change([], 0)

    def refresh(self, at):
        self.tree.delete(*self.tree.get_children())
        self.thumb.clear()
        for i in range(len(self.items)):
            self.tree.insert("", "end", iid=str(i), text=f"  {i + 1}")
        self.last_view = None
        self.displayed = None
        self.generation += 1
        if self.items:
            self.goto(at)
        else:
            self.canvas.delete("all")
            self.info.set("")
            self.status.set("PDFを開いてください。")

    def goto(self, n):
        if self.items:
            n = min(max(0, n), len(self.items) - 1)
            self.tree.selection_set(str(n))
            self.tree.focus(str(n))
            self.tree.see(str(n))
            self.choose()

    def choose(self, event=None):
        ids = self.selected()
        if not ids:
            return
        focus = self.tree.focus()
        self.active = int(focus) if focus and int(focus) in ids else ids[0]
        key = (self.active, self.zoom, self.generation)
        if self.last_view == key:
            return
        self.last_view = key
        self.rect = None
        leaf = self.items[self.active]
        self.photo = None
        self.canvas.delete("all")
        self.canvas.create_text(
            20, 20, text="ページを読み込み中…", anchor="nw", fill="#316766"
        )
        if not self.job:
            self.status.set("ページを読み込み中…")
        name = Path(leaf.path) if leaf.path else None
        self.info.set(
            f"{name.name if name else '空白ページ'}\n\n{self.active + 1} / {len(self.items)} ページ\n{self.zoom:.0%}"
            + (
                f"\n元ファイル {name.stat().st_size:,} B"
                if name and name.exists()
                else ""
            )
        )
        self.schedule_render()

    def visible_rows(self):
        if not self.items or not self.tree.winfo_ismapped():
            return set()
        return {
            self.tree.identify_row(y) for y in range(2, self.tree.winfo_height(), 24)
        } - {""}

    def schedule_render(self):
        if self.renderer.pending is not None or not self.items:
            return
        if self.last_view is not None and self.last_view != self.displayed:
            self.renderer.request(
                ("page", self.last_view), self.items[self.active], self.zoom
            )
            return
        visible = self.visible_rows()
        for iid in set(self.thumb) - visible:
            if self.tree.exists(iid):
                self.tree.item(iid, image="")
            del self.thumb[iid]
        missing = sorted(visible - set(self.thumb), key=int)
        if missing:
            iid = missing[0]
            self.renderer.request(
                ("thumb", (iid, self.generation)), self.items[int(iid)], 1, True
            )

    def thumbnails(self):
        render = self.renderer
        if render.pending is not None and render.pipe.poll():
            kind, key = render.pending
            try:
                blob, rect, error = render.pipe.recv()
            except (BrokenPipeError, EOFError, OSError):
                self.renderer.stop()
                self.renderer = Renderer()
                blob, rect, error = None, None, "ページの描画に失敗しました。"
            render.pending = None
            if kind == "page" and key == self.last_view:
                self.displayed = key
                self.canvas.delete("all")
                if error:
                    self.status.set(error)
                else:
                    self.dims = e.pdf.Rect(rect)
                    self.photo = ImageTk.PhotoImage(Image.open(io.BytesIO(blob)))
                    self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
                    self.canvas.config(
                        scrollregion=(0, 0, self.photo.width(), self.photo.height())
                    )
                    self.canvas.xview_moveto(0)
                    self.canvas.yview_moveto(0)
                    if not self.job:
                        self.status.set(
                            f"{self.active + 1} / {len(self.items)} ページ　{self.zoom:.0%}"
                        )
            elif (
                kind == "thumb"
                and key[1] == self.generation
                and key[0] in self.visible_rows()
            ):
                iid = key[0]
                self.thumb[iid] = (
                    None if error else ImageTk.PhotoImage(Image.open(io.BytesIO(blob)))
                )
                if self.thumb[iid]:
                    self.tree.item(iid, image=self.thumb[iid])
        self.schedule_render()
        self.root.after(30, self.thumbnails)

    def edit(self, kind):
        ids = self.selected()
        selected = set(ids)
        at = ids[0] if ids else 0
        if kind == "空白追加":
            self.change(self.items[:at] + [e.Leaf()] + self.items[at:], at)
            return
        if not ids:
            return
        if kind == "回転":
            new = [
                replace(x, turn=(x.turn + 90) % 360) if i in selected else x
                for i, x in enumerate(self.items)
            ]
        elif kind == "削除":
            new = [x for i, x in enumerate(self.items) if i not in selected]
        elif kind == "複製":
            new = [
                v
                for i, x in enumerate(self.items)
                for v in ([x, x] if i in selected else [x])
            ]
        else:
            self.move(
                ids,
                max(0, at - 1) if kind == "上へ" else min(len(self.items), ids[-1] + 2),
            )
            return
        self.change(new, at)

    def move(self, ids, target):
        chosen = set(ids)
        at = target - sum(i < target for i in ids)
        rest = [x for i, x in enumerate(self.items) if i not in chosen]
        self.change(rest[:at] + [self.items[i] for i in ids] + rest[at:], at)

    def reorder(self, ev):
        iid = self.tree.identify_row(ev.y)
        start = getattr(self, "dragrow", "")
        if start and iid and iid != start:
            ids = self.selected() if int(start) in self.selected() else [int(start)]
            self.move(ids, int(iid) + (int(iid) > int(start)))

    def scale(self, factor):
        self.zoom = min(5, max(0.15, self.zoom * factor))
        self.choose()
        return "break"

    def setmode(self, mode):
        self.mode.set(mode)
        self.status.set("ドラッグして範囲を選択してください。")

    def point(self, ev):
        return (
            max(0, min(self.dims.width, self.canvas.canvasx(ev.x) / self.zoom)),
            max(0, min(self.dims.height, self.canvas.canvasy(ev.y) / self.zoom)),
        )

    def down(self, ev):
        if not self.items or self.photo is None:
            return
        self.start = self.point(ev)
        self.initial = self.rect
        self.action = "new"
        if self.rect:
            a, b, c, d = self.rect
            x, y = self.start
            for hx, hy, ox, oy in [
                (a, b, c, d),
                (c, b, a, d),
                (a, d, c, b),
                (c, d, a, b),
            ]:
                if max(abs(hx - x), abs(hy - y)) * self.zoom < 9:
                    self.start = (ox, oy)
                    self.action = "resize"
                    return
            if a < x < c and b < y < d:
                self.action = "move"

    def motion(self, ev):
        if not self.items or not hasattr(self, "start"):
            return
        x, y = self.point(ev)
        sx, sy = self.start
        if self.action == "move":
            a, b, c, d = self.initial
            dx = max(-a, min(self.dims.width - c, x - sx))
            dy = max(-b, min(self.dims.height - d, y - sy))
            self.rect = (a + dx, b + dy, c + dx, d + dy)
        else:
            self.rect = (min(sx, x), min(sy, y), max(sx, x), max(sy, y))
        self.canvas.delete("selection")
        a, b, c, d = [v * self.zoom for v in self.rect]
        self.canvas.create_rectangle(
            a, b, c, d, outline="#008b91", width=2, tags="selection"
        )
        for x, y in ((a, b), (c, b), (a, d), (c, d)):
            self.canvas.create_rectangle(
                x - 3,
                y - 3,
                x + 3,
                y + 3,
                fill="white",
                outline="#008b91",
                tags="selection",
            )

    def up(self, ev):
        if not hasattr(self, "start"):
            return
        self.motion(ev)
        del self.start
        if self.rect and e.pdf.Rect(self.rect).get_area() > 1:
            if self.mode.get() == "画像コピー":
                self.image()
            if self.mode.get() == "文字スキャン":
                self.ocr()
        else:
            self.rect = None
            self.canvas.delete("selection")

    def has_rect(self):
        if self.items and self.rect:
            return True
        self.status.set("先にプレビュー上で範囲をドラッグしてください。")
        return False

    def image(self, save=False):
        if not self.has_rect():
            return
        dest = (
            files.asksaveasfilename(
                defaultextension=".png", filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg")]
            )
            if save
            else None
        )
        if save and not dest:
            return

        def done(blob):
            im = Image.open(io.BytesIO(blob))
            if dest:
                im.save(dest)
            else:
                win.copy_image(im)
            self.status.set(
                "画像を保存しました。"
                if dest
                else "画像をコピーしました。Ctrl + V で貼り付けできます。"
            )

        self.launch(
            "image", (self.items[self.active], self.dpi.get() / 72, self.rect), done
        )

    def ocr(self):
        if not self.has_rect():
            return

        def done(text):
            w = tk.Toplevel(self.root)
            w.title("文字スキャン結果")
            ttk.Label(
                w,
                text="文字を確認して修正できます。表・数式・縦書きでは誤認識が生じることがあります。",
            ).pack(padx=10, pady=8)
            box = tk.Text(w, width=64, height=12, wrap="word")
            box.pack(fill="both", expand=True)
            box.insert("1.0", text)

            def copy():
                self.root.clipboard_clear()
                self.root.clipboard_append(box.get("1.0", "end-1c"))
                w.destroy()

            ttk.Button(w, text="コピー", command=copy).pack(pady=6)

        self.launch("ocr", (self.items[self.active], self.rect, self.lang.get()), done)

    def crop_menu(self):
        self.setmode("範囲選択")
        if not self.has_rect():
            return
        w = tk.Toplevel(self.root)
        w.title("トリミング")
        ttk.Label(
            w,
            text="CropBoxで表示領域を変更します。枠外のデータはPDF内に残ります。",
            padding=10,
        ).pack()
        for name in ["現在", "指定ページ", "全ページ"]:
            ttk.Button(
                w, text=name, command=lambda n=name: (w.destroy(), self.apply_crop(n))
            ).pack(fill="x", padx=10, pady=3)

    def apply_crop(self, scope):
        if not self.items or (scope != "解除" and not self.has_rect()):
            return
        ids = self.selected() if scope == "解除" else [self.active]
        if scope == "全ページ":
            ids = range(len(self.items))
        if scope == "指定ページ":
            s = ask.askstring("一括適用", "ページ範囲（例 1-3, 5）")
            if not s:
                return
            ids = e.pages(s, len(self.items))
        snapshot = self.items

        def done(boxes):
            if self.items is not snapshot:
                self.status.set(
                    "処理中にページが変更されたためトリミングを再実行してください。"
                )
                return
            new = snapshot.copy()
            for i, crop in boxes:
                new[i] = replace(new[i], crop=crop)
            self.change(new, self.active)

        if scope == "解除":
            done([(i, None) for i in ids])
        else:
            self.launch("crop", (snapshot, list(ids), self.rect), done)

    def markbox(self, leaf):
        with e.Builder() as b:
            page = b.add(leaf)
            box = e.pdf.Rect(e.crop_coords(page, self.rect))
        with e.Builder() as b:
            pos = b.add(replace(leaf, crop=None, marks=())).cropbox_position
        return tuple(box - (pos.x, pos.y, pos.x, pos.y))

    def mark(self, kind):
        if not self.has_rect():
            return
        value = ""
        size = 12
        color = (0.12, 0.32, 0.49)
        if kind in ("文字", "メモ"):
            value = ask.askstring(kind, "追加する文字")
            if not value:
                return
        if kind == "文字":
            size = ask.askinteger(kind, "文字サイズ (pt)", initialvalue=14, minvalue=1)
            if not size:
                return
        if kind in ("文字", "線", "矢印", "四角形"):
            rgb = colorchooser.askcolor(title="色を選択")[0]
            if rgb is None:
                return
            color = tuple(c / 255 for c in rgb)
        if kind == "画像":
            name = files.askopenfilename(filetypes=[("画像", "*.png *.jpg *.jpeg")])
            if not name:
                return
            value = Path(name).read_bytes()
        leaf = self.items[self.active]
        self.update_leaf(
            replace(
                leaf,
                marks=leaf.marks + ((kind, self.markbox(leaf), value, size, color),),
            )
        )

    def update_leaf(self, leaf):
        new = self.items.copy()
        new[self.active] = leaf
        self.change(new, self.active)

    def reposition(self):
        if not self.has_rect():
            return
        leaf = self.items[self.active]
        if leaf.marks:
            kind, _, value, size, color = leaf.marks[-1]
            self.update_leaf(
                replace(
                    leaf,
                    marks=leaf.marks[:-1]
                    + ((kind, self.markbox(leaf), value, size, color),),
                )
            )

    def transfer(self, move):
        ids = self.selected()
        if not ids or self.job:
            return
        source = files.askopenfilename(
            title="挿入先のPDFを選択", filetypes=[("PDF", "*.pdf")]
        )
        if not source:
            return
        pw = ""
        while True:
            try:
                with e.open_pdf(source, pw) as doc:
                    count = len(doc)
                break
            except PermissionError:
                pw = ask.askstring("挿入先", "PDFのパスワード", show="*")
                if pw is None:
                    return
        after = ask.askinteger(
            "挿入位置",
            "何ページ目の後に追加しますか？（先頭は0）",
            initialvalue=count,
            minvalue=0,
            maxvalue=count,
        )
        if after is None:
            return
        dest = files.asksaveasfilename(
            title="編集した挿入先PDFを別名保存",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
        )
        if not dest:
            return
        snapshot = self.items
        target = [e.Leaf(source, i, pw) for i in range(count)]
        target[after:after] = [snapshot[i] for i in ids]

        def complete():
            if move and snapshot is self.items:
                chosen = set(ids)
                self.change(
                    [v for i, v in enumerate(snapshot) if i not in chosen], ids[0]
                )

        self.export([(target, Path(dest), None)], False, complete)

    def save(self, ids=None, comp=None):
        if not self.items:
            return
        leaves = self.items if ids is None else [self.items[i] for i in ids]
        if not leaves:
            return
        name = files.asksaveasfilename(
            defaultextension=".pdf", filetypes=[("PDF", "*.pdf")]
        )
        if name:
            self.export([(leaves, Path(name), comp)], ids is None)

    def split(self):
        if not self.items:
            return
        w = tk.Toplevel(self.root)
        w.title("分割・抽出")
        mode = tk.StringVar(value="範囲抽出")
        for name in [
            "範囲抽出",
            "奇数ページ",
            "偶数ページ",
            "指定枚数ごとに分割",
            "1ページずつ分割",
        ]:
            ttk.Radiobutton(w, text=name, value=name, variable=mode).pack(
                anchor="w", padx=12, pady=2
            )
        spec = tk.StringVar(value="1")
        ttk.Label(w, text="範囲（1-3, 5）または分割枚数").pack(padx=12)
        ttk.Entry(w, textvariable=spec).pack(fill="x", padx=12)

        def run():
            choice = mode.get()
            n = len(self.items)
            if choice == "範囲抽出":
                ids = e.pages(spec.get(), n)
            elif choice == "奇数ページ":
                ids = list(range(0, n, 2))
            elif choice == "偶数ページ":
                ids = list(range(1, n, 2))
            else:
                count = 1 if choice == "1ページずつ分割" else int(spec.get())
                if count < 1:
                    raise ValueError("1以上を指定してください。")
                directory = files.askdirectory()
                if not directory:
                    return
                groups = [
                    (
                        self.items[i : i + count],
                        Path(directory)
                        / f"pages-{i + 1:04d}-{min(i + count, n):04d}.pdf",
                        None,
                    )
                    for i in range(0, n, count)
                ]
                if any(p.exists() for _, p, _ in groups):
                    raise ValueError(
                        "同名のPDFがあります。別のフォルダーを選択してください。"
                    )
                w.destroy()
                self.export(groups, False)
                return
            w.destroy()
            self.save(ids)

        ttk.Button(w, text="保存先を選ぶ", command=run).pack(pady=8)

    def compress(self):
        if not self.items:
            self.open()
            if not self.items:
                return
        w = tk.Toplevel(self.root)
        w.title("PDFを圧縮")
        mode = tk.StringVar(value="標準")
        for label in ["ロスレス", "標準", "高圧縮", "カスタム", "ページ全体を画像化"]:
            ttk.Radiobutton(w, text=label, value=label, variable=mode).pack(
                anchor="w", padx=14
            )
        dpi = tk.IntVar(value=150)
        quality = tk.IntVar(value=75)
        for label, var, lo, hi in [
            ("カスタム画像解像度 (dpi)", dpi, 36, 1200),
            ("JPEG品質", quality, 1, 100),
        ]:
            ttk.Label(w, text=label).pack()
            ttk.Spinbox(w, from_=lo, to=hi, textvariable=var).pack(padx=14)

        def go():
            cfg = {
                "ロスレス": (0, 0),
                "標準": (150, 75),
                "高圧縮": (96, 48),
                "カスタム": (dpi.get(), quality.get()),
                "ページ全体を画像化": (dpi.get(), quality.get(), "raster"),
            }[mode.get()]
            if cfg[0] and (cfg[0] < 1 or not 1 <= cfg[1] <= 100):
                raise ValueError("解像度または品質が範囲外です。")
            if mode.get() == "ページ全体を画像化":
                if not msg.askyesno(
                    "画像化を確認",
                    "ページ全体をJPEGにします。検索・文字選択・リンク・フォーム操作が失われ、拡大時の画質が変わります。続けますか？",
                ):
                    return
            w.destroy()
            self.save(comp=cfg)

        ttk.Button(w, text="圧縮して保存", command=go).pack(pady=8)

    def export(self, groups, whole, completed=None):
        if self.job:
            return
        sources = {Path(x.path).resolve() for x in self.items if x.path}
        snapshot = self.items
        stages = []
        payload = []
        try:
            import shutil

            baseline = sum(p.stat().st_size for p in sources)
            free = shutil.disk_usage(groups[0][1].parent).free
            if free < baseline and not msg.askyesno(
                "空き容量の確認",
                f"元PDF合計 {baseline:,} B、空き容量 {free:,} B。出力サイズによっては保存できません。続けますか？",
            ):
                return
            for leaves, dest, comp in groups:
                if dest.resolve() in sources or any(
                    x.path and Path(x.path).resolve() == dest.resolve() for x in leaves
                ):
                    raise ValueError("元PDFとは別のファイル名を指定してください。")
                if shutil.disk_usage(dest.parent).free < 4096:
                    raise OSError("空き容量が不足しています。")
                fd, stage = tempfile.mkstemp(dir=dest.parent, suffix=".part")
                os.close(fd)
                stages.append((Path(stage), dest))
                payload.append((leaves, stage, comp))
            self.stages = stages
            start = time.monotonic()
            before = sum(p.stat().st_size for p in sources)

            def done(_):
                for stage, dest in stages:
                    os.replace(stage, dest)
                if whole and snapshot is self.items:
                    self.dirty = False
                total = sum(dest.stat().st_size for _, dest in stages)
                self.status.set(f"保存完了　{len(stages)} ファイル　{total:,} B")
                if completed:
                    completed()
                if groups[0][2]:
                    msg.showinfo(
                        "圧縮結果",
                        f"元PDF合計　{before:,} B\n出力　{total:,} B\n削減量　{before - total:,} B（{(1 - total / before) * 100 if before else 0:.1f}%）\n処理時間　{time.monotonic() - start:.2f} 秒"
                        + (
                            "\n元ファイルより容量が増えました。"
                            if total > before
                            else ""
                        ),
                    )

            self.launch("save", payload, done)
        except Exception:
            for stage, _ in stages:
                stage.unlink(missing_ok=True)
            raise

    def launch(self, op, payload, done):
        if self.job:
            self.status.set("実行中の処理が終わるまでお待ちください。")
            return
        read, write = mp.Pipe(False)
        proc = mp.Process(target=worker, args=(write, op, payload), daemon=True)
        proc.start()
        write.close()
        self.job = (proc, read, done)
        self.status.set("処理中…")
        self.cancel_btn.configure(state="normal")
        self.bar.configure(mode="indeterminate")
        self.bar.start()
        self.root.after(80, self.poll)

    def poll(self):
        if not self.job:
            return
        proc, read, done = self.job
        if read.poll():
            try:
                kind, value = read.recv()
            except EOFError:
                kind, value = "error", "処理が中断されました。"
            if kind == "progress":
                self.bar.stop()
                self.bar.configure(mode="determinate", value=value * 100)
            else:
                try:
                    self.status.set("処理完了")
                    if kind == "ok":
                        done(value)
                    else:
                        msg.showerror("処理エラー", value)
                finally:
                    self.finish()
                return
        self.root.after(60, self.poll)

    def finish(self):
        proc, read, _ = self.job
        proc.join()
        read.close()
        proc.close()
        self.job = None
        self.bar.stop()
        self.bar.configure(value=0)
        self.cancel_btn.configure(state="disabled")
        for path, _ in self.stages:
            path.unlink(missing_ok=True)
        self.stages = []

    def cancel(self):
        if self.job:
            self.job[0].terminate()
            self.finish()
            self.status.set("キャンセルしました。")

    def settings(self):
        w = tk.Toplevel(self.root)
        w.title("設定")
        dark = tk.BooleanVar(value=self.prefs.get("dark", False))
        hide = tk.BooleanVar(value=self.prefs.get("hide", False))
        startup = tk.BooleanVar(value=win.autostart_enabled())
        for title, var in [
            ("ダークモード", dark),
            ("閉じるボタンでトレイに格納", hide),
            ("Windows起動時に自動起動", startup),
        ]:
            ttk.Checkbutton(w, text=title, variable=var).pack(
                anchor="w", padx=12, pady=3
            )
        ttk.Label(w, text="画像コピー解像度 (dpi)").pack()
        dpi = tk.IntVar(value=self.dpi.get())
        lang = tk.StringVar(value=self.lang.get())
        ttk.Spinbox(w, textvariable=dpi, from_=36, to=1200).pack()
        ttk.Label(w, text="OCR言語（jpn_vert は縦書き）").pack()
        ttk.Combobox(
            w,
            textvariable=lang,
            values=["jpn+eng", "jpn", "eng", "jpn_vert"],
            state="readonly",
        ).pack(padx=12)

        def apply():
            if not 36 <= dpi.get() <= 1200:
                raise ValueError("解像度は36～1200 dpiです。")
            win.set_autostart(startup.get())
            self.dpi.set(dpi.get())
            self.lang.set(lang.get())
            self.prefs.update(
                dark=dark.get(), hide=hide.get(), dpi=dpi.get(), lang=lang.get()
            )
            win.save_prefs(self.prefs)
            self.theme()
            w.destroy()

        ttk.Button(w, text="設定を保存", command=apply).pack(pady=9)

    def close(self):
        if self.prefs.get("hide", False) and not self.tray.error:
            self.root.withdraw()
        else:
            self.quit()

    def quit(self):
        if self.dirty and not msg.askyesno(
            "終了", "保存されていない作業があります。終了しますか？"
        ):
            return
        self.closed = True
        self.cancel()
        self.renderer.stop()
        self.tray.stop()
        self.root.destroy()


def main():
    mp.freeze_support()
    if "--self-test" in sys.argv:
        from smoke_checks import run

        run()
        return
    lock = win.single()
    if lock is None:
        return
    root = TkinterDnD.Tk()
    root.report_callback_exception = lambda typ, err, tb: msg.showerror(
        "chun PDF", str(err)
    )
    app = App(root, "--tray" in sys.argv)
    if win.autostart_enabled():
        win.set_autostart(True)
    paths = [p for p in sys.argv[1:] if not p.startswith("--")]
    if paths:
        app.load(paths)
    root.mainloop()


if __name__ == "__main__":
    main()
