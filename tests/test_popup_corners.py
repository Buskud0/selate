"""Corner transparency regression tests.

These spawn a real Tk window and read its rendered surface via PrintWindow,
so they require an interactive desktop session. They verify that the popup's
rounded corners never show the BACKGROUND color (i.e. the color-key
transparency is active after show, after resize, and crucially after a resize
that was interrupted without a release).
"""

import ctypes
import time
import unittest
from ctypes import wintypes

import win32gui

import popup_draw as pd
from popup import CoverPopup

BACKGROUND_HEX = '#f0f4fa'


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ('biSize', wintypes.DWORD),
        ('biWidth', wintypes.LONG),
        ('biHeight', wintypes.LONG),
        ('biPlanes', wintypes.WORD),
        ('biBitCount', wintypes.WORD),
        ('biCompression', wintypes.DWORD),
        ('biSizeImage', wintypes.DWORD),
        ('biXPelsPerMeter', wintypes.LONG),
        ('biYPelsPerMeter', wintypes.LONG),
        ('biClrUsed', wintypes.DWORD),
        ('biClrImportant', wintypes.DWORD),
    ]


def _grab_window(hwnd):
    rect = win32gui.GetWindowRect(hwnd)
    w = rect[2] - rect[0]
    h = rect[3] - rect[1]
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
    screen = user32.GetDC(0)
    mem = gdi32.CreateCompatibleDC(screen)
    bmp = gdi32.CreateCompatibleBitmap(screen, w, h)
    gdi32.SelectObject(mem, bmp)
    user32.PrintWindow(hwnd, mem, 2)
    header = BITMAPINFOHEADER()
    header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    header.biWidth = w
    header.biHeight = -h
    header.biPlanes = 1
    header.biBitCount = 32
    header.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(header), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(0, screen)
    return buf.raw, w, h


def _corner_colors(hwnd):
    raw, w, h = _grab_window(hwnd)
    points = [
        ('tl', 2, 2),
        ('tr', w - 3, 2),
        ('bl', 2, h - 3),
        ('br', w - 3, h - 3),
    ]
    colors = {}
    for name, px, py in points:
        i = (py * w + px) * 4
        colors[name] = '#%02X%02X%02X' % (raw[i + 2], raw[i + 1], raw[i])
    return colors


def _background_corners(colors):
    return [name for name, value in colors.items()
            if value.lower() == BACKGROUND_HEX]


class PopupCornersTest(unittest.TestCase):

    def setUp(self):
        self.popup = CoverPopup()
        self.popup.start()
        self.popup.wait_ready(10)
        time.sleep(0.3)

    def tearDown(self):
        self.popup.destroy()

    def assert_transparent_corners(self, label):
        colors = _corner_colors(self.popup._window.winfo_id())
        bad = _background_corners(colors)
        self.assertEqual([], bad, f'{label}: background corners at {bad}: {colors}')

    def test_normal_show_has_transparent_corners(self):
        self.popup.show_translation('Testas', {})
        time.sleep(0.8)
        self.assert_transparent_corners('normal show')

    def test_resize_cycle_leaves_transparent_corners(self):
        self.popup.show_translation('Testas', {})
        time.sleep(0.5)
        self.popup._window.after(0, self.popup._begin_resize_surface)
        time.sleep(0.3)
        self.popup._window.after(
            0, lambda: self.popup._window.geometry('260x140+320+320')
        )
        time.sleep(0.3)
        self.popup._window.after(0, self.popup._end_resize_surface)
        time.sleep(0.5)
        self.assert_transparent_corners('after resize cycle')

    def test_interrupted_resize_then_show_recovers(self):
        self.popup.show_translation('Testas', {})
        time.sleep(0.5)
        # Start a resize and never complete it (missed ButtonRelease, Escape
        # or hide during a corner drag leaves the surface stuck).
        self.popup._window.after(0, self.popup._begin_resize_surface)
        time.sleep(0.4)
        stuck = _corner_colors(self.popup._window.winfo_id())
        self.assertTrue(
            _background_corners(stuck),
            f'precondition: stuck resize surface should show background corners: {stuck}',
        )
        # A new translation/show must recover to a transparent surface.
        self.popup.show_translation('Antras', {})
        time.sleep(0.8)
        self.assert_transparent_corners('show after interrupted resize')


if __name__ == '__main__':
    unittest.main()
