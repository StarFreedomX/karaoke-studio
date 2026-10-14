from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

from krok_helper import logging_config


def test_get_log_dir_honors_explicit_environment(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "diagnostics"
    monkeypatch.setenv(logging_config.LOG_DIR_ENV, str(target))

    assert logging_config.get_log_dir() == target
    assert logging_config.get_log_path() == target / logging_config.LOG_FILE_NAME


def test_configure_application_logging_writes_rotating_redacted_log(tmp_path: Path) -> None:
    root_logger = logging.getLogger()
    old_level = root_logger.level
    log_path = logging_config.configure_application_logging(
        tmp_path,
        enable_native_crash_log=False,
        install_exception_hooks=False,
        install_qt_handler=False,
    )
    handler = next(
        item
        for item in root_logger.handlers
        if getattr(item, logging_config._HANDLER_MARKER, False)
    )
    try:
        assert isinstance(handler, logging.handlers.RotatingFileHandler)
        assert handler.maxBytes == logging_config.MAX_LOG_BYTES
        assert handler.backupCount == logging_config.LOG_BACKUP_COUNT

        logging.getLogger("tests.logging").error(
            "request=https://alice:secret@example.test/file?access_token=abc123 Cookie: session-secret"
        )
        handler.flush()
        contents = log_path.read_text(encoding="utf-8")
        assert "tests.logging" in contents
        assert "alice" not in contents
        assert "secret" not in contents
        assert "abc123" not in contents
        assert "session-secret" not in contents
        assert "https://***:***@example.test/file?access_token=***" in contents
    finally:
        root_logger.removeHandler(handler)
        handler.close()
        root_logger.setLevel(old_level)
        logging_config._configured_log_path = None


def test_font_diagnostics_disabled_leaves_logging_rules_unchanged(monkeypatch) -> None:
    monkeypatch.delenv(logging_config.FONT_TRACE_ENV, raising=False)
    monkeypatch.setenv("QT_LOGGING_RULES", "qt.test.debug=false")

    assert logging_config.install_font_diagnostics() is False
    assert os.environ["QT_LOGGING_RULES"] == "qt.test.debug=false"


def test_font_trace_full_queue_does_not_wait_for_disk() -> None:
    recorder = logging_config._FontTraceRecorder.__new__(logging_config._FontTraceRecorder)
    recorder.pending = queue.Queue(maxsize=1)
    recorder.pending.put_nowait("occupied")
    recorder.dropped = 0
    producer = threading.Thread(target=recorder.emit, args=("font", "sample"), daemon=True)
    producer.start()
    producer.join(timeout=1)

    assert not producer.is_alive(), "Qt's font-lock owner must never wait for the log writer"
    assert recorder.dropped == 1
    assert recorder.pending.get_nowait() == "occupied"


def test_font_trace_preserves_warning_handler() -> None:
    from PyQt6.QtCore import QtMsgType

    recorder = logging_config._FontTraceRecorder.__new__(logging_config._FontTraceRecorder)
    forwarded = []
    recorder.previous_handler = lambda *args: forwarded.append(args)
    context = SimpleNamespace(category="qt.text.font.match")

    recorder.capture(QtMsgType.QtCriticalMsg, context, "font failure")

    assert forwarded == [(QtMsgType.QtCriticalMsg, context, "font failure")]


def test_font_trace_logs_real_matching_and_font_changes_in_fresh_process(tmp_path) -> None:
    # A subprocess owns its logging rules, message handler and QApplication,
    # so this diagnostic test cannot change fonts in the shared GUI test app.
    code = r'''
import sys
from PyQt6.QtGui import QFont, QFontMetrics
from PyQt6.QtWidgets import QApplication
from krok_helper import logging_config

path = logging_config.configure_application_logging(
    sys.argv[1], enable_native_crash_log=False, install_exception_hooks=False,
)
assert logging_config.install_font_diagnostics()
app = QApplication([])
before = app.font().toString()
assert logging_config.install_font_diagnostics(app)
assert app.font().toString() == before
font = QFont("Microsoft YaHei", 22)
requested = font.toString()
QFontMetrics(font).horizontalAdvance("한글0123中文あいう")
assert font.toString() == requested
app.setFont(QFont("Arial", 13))
logging_config._font_trace_recorder.stop()
print(path)
'''
    env = dict(os.environ, KARAOKE_STUDIO_FONT_TRACE="1", PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)], env=env,
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stderr
    contents = (tmp_path / logging_config.LOG_FILE_NAME).read_text(encoding="utf-8")
    assert "category=qt.text.font.match" in contents
    assert "category=application-font-initial" in contents
    assert "category=application-font-changed" in contents
    assert "origin=MainThread" in contents
