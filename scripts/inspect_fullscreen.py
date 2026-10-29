"""Read-only Win32 geometry/visibility evidence; never captures titles or content."""
import argparse
import ctypes as c
from ctypes import wintypes as w
import json
import time
from pathlib import Path

u = c.WinDLL("user32", use_last_error=True)
u.SetProcessDPIAware()
u.GetForegroundWindow.restype = w.HWND
u.GetWindowLongPtrW.argtypes = [w.HWND, c.c_int]
u.GetWindowLongPtrW.restype = c.c_ssize_t
u.WindowFromPoint.argtypes = [w.POINT]
u.WindowFromPoint.restype = w.HWND
u.GetAncestor.argtypes = [w.HWND, w.UINT]
u.GetAncestor.restype = w.HWND
u.MonitorFromWindow.argtypes = [w.HWND, w.DWORD]
u.MonitorFromWindow.restype = w.HANDLE
for name in ("GetWindowRect", "GetWindowThreadProcessId", "GetClassNameW", "IsWindowVisible", "IsIconic", "IsZoomed"):
    getattr(u, name).argtypes = [w.HWND] + ({"GetWindowRect": [c.POINTER(w.RECT)], "GetWindowThreadProcessId": [c.POINTER(w.DWORD)], "GetClassNameW": [w.LPWSTR, c.c_int]}.get(name, []))

class MonitorInfo(c.Structure):
    _fields_ = [("size", w.DWORD), ("monitor", w.RECT), ("work", w.RECT), ("flags", w.DWORD)]

u.GetMonitorInfoW.argtypes = [w.HANDLE, c.POINTER(MonitorInfo)]
callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
u.EnumWindows.argtypes = [callback_type, w.LPARAM]
u.EnumChildWindows.argtypes = [w.HWND, callback_type, w.LPARAM]

def rect_list(rect):
    return [rect.left, rect.top, rect.right, rect.bottom]

def info(hwnd):
    pid, rect, cls = w.DWORD(), w.RECT(), c.create_unicode_buffer(256)
    u.GetWindowThreadProcessId(hwnd, c.byref(pid))
    u.GetWindowRect(hwnd, c.byref(rect))
    u.GetClassNameW(hwnd, cls, len(cls))
    result = dict(hwnd=hwnd, pid=pid.value, cls=cls.value, rect=rect_list(rect),
                style=hex(u.GetWindowLongPtrW(hwnd, -16) & 0xffffffff),
                extended_style=hex(u.GetWindowLongPtrW(hwnd, -20) & 0xffffffff),
                visible=bool(u.IsWindowVisible(hwnd)), minimized=bool(u.IsIconic(hwnd)),
                maximized=bool(u.IsZoomed(hwnd)))
    if cls.value == "Tauri Window" and rect.right > rect.left and rect.bottom > rect.top:
        hit = u.WindowFromPoint(w.POINT((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2))
        root = u.GetAncestor(hit, 2) if hit else None
        result["center_hit_root"] = root
        result["center_is_top_window"] = root == hwnd
    return result

def snapshot(target, overlay_pid):
    fg = u.GetForegroundWindow()
    monitor = MonitorInfo(size=c.sizeof(MonitorInfo))
    u.GetMonitorInfoW(u.MonitorFromWindow(target or fg, 2), c.byref(monitor))
    result = dict(time=time.time(), foreground=info(fg), monitor=rect_list(monitor.monitor),
                  work=rect_list(monitor.work), windows=[])
    target_pid = info(target)["pid"] if target else result["foreground"]["pid"]
    @callback_type
    def child(hwnd, _):
        item = info(hwnd)
        if item["visible"]:
            result["windows"].append(item)
        return True
    @callback_type
    def top(hwnd, _):
        item = info(hwnd)
        if item["pid"] in (target_pid, overlay_pid):
            result["windows"].append(item)
            u.EnumChildWindows(hwnd, child, 0)
        return True
    u.EnumWindows(top, 0)
    return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=0)
    parser.add_argument("--overlay-pid", type=int, default=0)
    parser.add_argument("--seconds", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    samples = []
    for _ in range(max(1, args.seconds)):
        samples.append(snapshot(args.target, args.overlay_pid))
        if args.seconds:
            time.sleep(1)
    payload = json.dumps(samples, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload)
