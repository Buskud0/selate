import win32api
import win32con

WorkArea = tuple[int, int, int, int]


def work_area_at(x: int, y: int) -> WorkArea:
    """Return the work area (left, top, right, bottom) of the monitor at (x, y)."""
    monitor = win32api.MonitorFromPoint(
        (int(x), int(y)), win32con.MONITOR_DEFAULTTONEAREST
    )
    return win32api.GetMonitorInfo(monitor)['Work']


def primary_work_area() -> WorkArea:
    """Return the work area (left, top, right, bottom) of the primary monitor."""
    monitor = win32api.MonitorFromPoint(
        (0, 0), win32con.MONITOR_DEFAULTTONEAREST
    )
    return win32api.GetMonitorInfo(monitor)['Work']
