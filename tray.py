"""Notification area icon with a Windows message loop on its own thread."""

import threading
import win32api
import win32con as c
import win32gui as g


class Tray:
    SIGNAL = c.WM_APP + 14

    def __init__(self, icon, commands, dispatch):
        self.commands = commands
        self.dispatch = dispatch
        self.icon_path = str(icon)
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.hwnd = None
        self.error = None
        self.thread.start()
        self.ready.wait(5)

    def run(self):
        try:
            wc = g.WNDCLASS()
            wc.hInstance = win32api.GetModuleHandle(None)
            wc.lpszClassName = "ChunPDF.Tray"
            wc.lpfnWndProc = {
                self.SIGNAL: self.click,
                c.WM_COMMAND: self.command,
                c.WM_DESTROY: self.destroy,
                g.RegisterWindowMessage("TaskbarCreated"): self.install_icon,
            }
            atom = g.RegisterClass(wc)
            self.hwnd = g.CreateWindow(
                atom, "", 0, 0, 0, 0, 0, 0, 0, wc.hInstance, None
            )
            self.icon = g.LoadImage(
                0,
                self.icon_path,
                c.IMAGE_ICON,
                0,
                0,
                c.LR_LOADFROMFILE | c.LR_DEFAULTSIZE,
            )
            self.install_icon()
            self.ready.set()
            g.PumpMessages()
        except Exception as exc:
            self.error = exc
        finally:
            self.ready.set()

    def install_icon(self, *args):
        data = (
            self.hwnd,
            1,
            g.NIF_MESSAGE | g.NIF_ICON | g.NIF_TIP,
            self.SIGNAL,
            self.icon,
            "chun PDF",
        )
        g.Shell_NotifyIcon(g.NIM_ADD, data)
        return 0

    def click(self, hwnd, msg, w, l):
        if l == c.WM_LBUTTONDBLCLK:
            self.dispatch(self.commands[0][1])
        elif l == c.WM_RBUTTONUP:
            menu = g.CreatePopupMenu()
            try:
                for i, (label, _) in enumerate(self.commands, 1):
                    g.AppendMenu(menu, c.MF_STRING, i, label)
                x, y = g.GetCursorPos()
                g.SetForegroundWindow(hwnd)
                g.TrackPopupMenu(
                    menu, c.TPM_LEFTALIGN | c.TPM_RIGHTBUTTON, x, y, 0, hwnd, None
                )
                g.PostMessage(hwnd, c.WM_NULL, 0, 0)
            finally:
                g.DestroyMenu(menu)
        return 0

    def command(self, hwnd, msg, w, l):
        i = (w & 65535) - 1
        if 0 <= i < len(self.commands):
            self.dispatch(self.commands[i][1])
        return 0

    def destroy(self, *args):
        g.Shell_NotifyIcon(g.NIM_DELETE, (self.hwnd, 1))
        g.DestroyIcon(self.icon)
        g.PostQuitMessage(0)
        return 0

    def stop(self):
        if self.hwnd and self.thread.is_alive():
            g.PostMessage(self.hwnd, c.WM_CLOSE, 0, 0)
            self.thread.join(3)
