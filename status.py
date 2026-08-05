"""Model status presentation and status-popup gating (single responsibility:
turning the internal model state into a UI decision)."""

import messages

LOADING_TEXTS = (
    messages.TEXT_CHECKING,
    messages.TEXT_INITIALIZING,
    messages.TEXT_DOWNLOADING,
)

_STATUS_TEXT = {
    'checking': messages.TEXT_CHECKING,
    'loading': messages.TEXT_LOADING,
    'downloading': messages.TEXT_DOWNLOADING,
    'initializing': messages.TEXT_INITIALIZING,
    'error': messages.TEXT_MODEL_ERROR,
    'ready': None,
}


def status_text(state, download_progress=None):
    """Return the display string for a model state, or None when ready."""
    if state == 'downloading' and download_progress is not None:
        try:
            downloaded, total = download_progress()
            if total:
                return (
                    f'{messages.TEXT_DOWNLOADING} '
                    f'{downloaded / 1024 / 1024:.0f} / {total / 1024 / 1024:.0f} MB'
                )
        except Exception:
            pass
    return _STATUS_TEXT.get(state, messages.TEXT_DOWNLOADING)


def should_show_status(text, settings):
    """Return whether a status popup should be shown for the given text."""
    if not settings.get('notifications', True):
        return False
    if text == messages.TEXT_CHECKING:
        return settings.get('notify_model_checking', False)
    if text == messages.TEXT_DOWNLOADING:
        return settings.get('notify_model_downloading', True)
    if text == messages.TEXT_INITIALIZING:
        return settings.get('notify_model_initializing', False)
    if text == messages.SELECT_HINT_TEXT:
        return settings.get('notify_selecting', False)
    if text == messages.TRANSLATING_TEXT:
        return settings.get('notify_translating', True)
    return True
