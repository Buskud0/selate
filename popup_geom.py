"""Geometry, sizing and placement helpers for the Selate popup."""

import screen

MAX_WIDTH = 1200
DEFAULT_WIDTH = 600
TEXT_PADDING = 10
SCROLL_STEP = 32
CORNER = 16
MIN_WIDTH = 80
MIN_HEIGHT = 40
EMPTY_POPUP_WIDTH = 70
EMPTY_POPUP_HEIGHT = 40


def _clamp(value, minimum, maximum):
    return max(minimum, min(value, maximum))


def _corner_at(x, y, width, height):
    if x <= CORNER and y <= CORNER:
        return 'nw'
    if x >= width - CORNER and y <= CORNER:
        return 'ne'
    if x <= CORNER and y >= height - CORNER:
        return 'sw'
    if x >= width - CORNER and y >= height - CORNER:
        return 'se'
    return None


def _resize_cursor(mode):
    return {
        'nw': 'size_nw_se', 'se': 'size_nw_se',
        'ne': 'size_ne_sw', 'sw': 'size_ne_sw',
        'n': 'size_ns', 's': 'size_ns',
        'e': 'size_we', 'w': 'size_we',
    }.get(mode, 'arrow')


def _target_work_area(anchor, pos):
    if anchor:
        return screen.work_area_at(int(anchor[0]), int(anchor[1]))
    if pos == 'se':
        try:
            import win32api
            return screen.work_area_at(*win32api.GetCursorPos())
        except Exception:
            pass
    return screen.primary_work_area()


def _fit_text_size(full_width, full_height, work):
    left, top, right, bottom = work
    max_w = max(120, min(MAX_WIDTH, right - left - 32))
    max_h = max(80, bottom - top - 32)
    width = _clamp(full_width, MIN_WIDTH, max_w)
    height = _clamp(full_height, MIN_HEIGHT, max_h)
    scroll_max = max(0, full_height - height)
    return width, height, scroll_max


def _text_x_for(width, pos):
    if pos == 'se':
        return width - TEXT_PADDING
    return width // 2


def _text_wrap_width(font, text, width):
    return max(1, min(font.measure(text), width - 2 * TEXT_PADDING))


def _wrap_width(font, text, work):
    max_w = max(120, min(MAX_WIDTH, work[2] - work[0] - 32))
    return max(1, min(max_w - 2 * TEXT_PADDING, font.measure(text)))


def _default_translation_size(font, text, work):
    """Size the popup to its text, up to DEFAULT_WIDTH before wrapping."""
    left, top, right, bottom = work
    max_w = max(120, min(MAX_WIDTH, right - left - 32))
    max_h = max(80, bottom - top - 32)
    max_default_width = min(DEFAULT_WIDTH, max_w)
    text_width = max((font.measure(line) for line in text.split('\n')), default=0)
    width = _clamp(text_width + 2 * TEXT_PADDING, MIN_WIDTH, max_default_width)
    wrap = max(1, width - 2 * TEXT_PADDING)
    _, full_height = _size_for_text(text, font, TEXT_PADDING, wrap)
    height = _clamp(full_height, MIN_HEIGHT, max_h)
    scroll_max = max(0, full_height - height)
    return width, height, scroll_max


def _size_for_text(text, font, padding, wrap_width=None):
    if not text:
        return EMPTY_POPUP_WIDTH, EMPTY_POPUP_HEIGHT
    if wrap_width is None:
        wrap_width = min(MAX_WIDTH - 2 * padding, font.measure(text))
    wrap_width = max(1, wrap_width)
    line_height = font.metrics('linespace')
    lines = _count_lines(text, wrap_width, font)
    width = wrap_width + 2 * padding
    height = max(1, lines) * line_height + 2 * padding
    return width, height


def _count_lines(text, wrap_width, font):
    if not text:
        return 1
    total = 0
    for paragraph in text.split('\n'):
        words = paragraph.split(' ')
        lines = 1
        current = ''
        for word in words:
            candidate = current + (' ' if current else '') + word
            if font.measure(candidate) <= wrap_width or not current:
                current = candidate
            else:
                lines += 1
                current = word
        total += lines
    return total


def _center(window, width, height):
    _place(window, width, height, None)


def _place(window, width, height, center):
    if center is None:
        work = screen.primary_work_area()
        left, top, right, bottom = work
        cx = left + (right - left) // 2
        cy = top + (bottom - top) // 2
    else:
        cx, cy = center
    x = cx - width // 2
    y = cy - height // 2
    window.geometry(f'{int(width)}x{int(height)}+{int(x)}+{int(y)}')


def _place_se(window, width, height):
    try:
        import win32api
        mx, my = win32api.GetCursorPos()
        work = screen.work_area_at(mx, my)
    except Exception:
        work = screen.primary_work_area()
    left, top, right, bottom = work
    x = right - width - 16
    y = bottom - height - 12
    window.geometry(f'{int(width)}x{int(height)}+{int(x)}+{int(y)}')


def _place_at(window, width, height, anchor):
    if anchor:
        ax, ay = anchor
        work = screen.work_area_at(ax, ay)
        left, top, right, bottom = work
        cx = left + (right - left) // 2
        x = cx - width // 2
        y = ay - height // 2
        y = max(top, min(y, bottom - height))
    else:
        work = screen.primary_work_area()
        left, top, right, bottom = work
        x = left + (right - left - width) // 2
        y = top + (bottom - top - height) // 2
    window.geometry(f'{int(width)}x{int(height)}+{int(x)}+{int(y)}')


def _offset_from_index(editor, index):
    counted = editor.count('1.0', index, 'chars')
    if isinstance(counted, int):
        return max(0, counted)
    if isinstance(counted, tuple) and counted:
        return max(0, counted[0])
    return 0


def _sel_range(editor):
    try:
        ranges = editor.tag_ranges('sel')
    except Exception:
        return None
    if not ranges:
        return None
    return _offset_from_index(editor, ranges[0]), _offset_from_index(editor, ranges[1])
