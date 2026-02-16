#!/usr/bin/env python3
"""Refactored ANT+ Heart Rate Monitor with model/UI separation."""
import sys
import logging
import threading
import platform
from ctypes import c_void_p
from PyQt6.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QObject
from PyQt6.QtGui import QFont, QKeySequence, QShortcut, QPalette, QColor

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    from openant.easy.node import Node
    from openant.devices.heart_rate import HeartRate
except ImportError:
    print("Error: openant not installed. Run: pip install openant")
    sys.exit(1)


class SafeHeartRate(HeartRate):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._attached = getattr(self, '_attached', False)

    def _on_data(self, data):
        try:
            super()._on_data(data)
        except Exception as e:
            if "CHANNEL_IN_WRONG_STATE" in str(e) or "error 21" in str(e):
                if len(data) > 8 and not self._attached:
                    self.device_id = data[9] + (data[10] << 8)
                    self.trans_type = data[12]
                    self._attached = True
                try:
                    self.on_data(data)
                    if hasattr(self, 'on_device_data') and self.on_device_data and len(data) >= 8:
                        from openant.devices.heart_rate import HeartRateData
                        hr_data = HeartRateData()
                        hr_data.heart_rate = data[7]
                        hr_data.beat_time = int.from_bytes(data[4:6], byteorder="little") / 1024
                        hr_data.beat_count = data[6]
                        self.on_device_data(data[0], "heart_rate", hr_data)
                except Exception:
                    pass
            else:
                raise


class AntWorker(QThread):
    bpm_update = pyqtSignal(int)
    status_update = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.running = True
        self.node = None

    def run(self):
        self.status_update.emit("Connecting to ANT+...")
        try:
            self.node = Node()
            self.node.set_network_key(0x00, [0xB9, 0xA5, 0x21, 0xFB, 0xBD, 0x72, 0xC3, 0x45])
            hr_sensor = SafeHeartRate(self.node, device_id=42687, trans_type=209)

            def on_found():
                self.status_update.emit("Heart rate sensor found!")

            def on_device_data(page, page_name, data):
                try:
                    bpm = data.heart_rate
                    if bpm > 0:
                        self.bpm_update.emit(bpm)
                        self.status_update.emit("Connected")
                except Exception:
                    pass

            hr_sensor.on_found = on_found
            hr_sensor.on_device_data = on_device_data

            def run_node():
                try:
                    self.node.start()
                except Exception:
                    pass

            t = threading.Thread(target=run_node, daemon=True)
            t.start()
            while self.running:
                self.msleep(100)
        except Exception as e:
            self.status_update.emit(f"Error: {e}")

    def stop(self):
        self.running = False
        if self.node:
            try:
                self.node.stop()
            except Exception:
                pass
        self.quit()
        self.wait()


class Model(QObject):
    bpm_changed = pyqtSignal(int)
    status_changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.worker = AntWorker()
        self.worker.bpm_update.connect(self.bpm_changed)
        self.worker.status_update.connect(self.status_changed)

    def start(self):
        self.worker.start()

    def stop(self):
        self.worker.stop()


class OverlayWindow(QMainWindow):
    closed = pyqtSignal()

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        central = QWidget()
        central.setObjectName("overlayCentral")
        central.setStyleSheet("background: transparent;")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.bpm_label = QLabel("--")
        self.bpm_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bpm_label.setFont(QFont("Arial", 72, QFont.Weight.Bold))
        self.bpm_label.setStyleSheet("color: rgba(255,255,255,230); background-color: rgba(0,0,0,140); padding:8px; border-radius:6px;")
        layout.addWidget(self.bpm_label)

        # Shortcuts to close overlay
        sc_o = QShortcut(QKeySequence('O'), self, activated=self.close_overlay)
        sc_o.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc_esc = QShortcut(QKeySequence('Esc'), self, activated=self.close_overlay)
        sc_esc.setContext(Qt.ShortcutContext.ApplicationShortcut)

        # Drag/resize state
        self._drag_pos = None
        self._resizing = False
        self._resize_start = None
        self._mouse_start = None

    def set_bpm(self, bpm: int):
        self.bpm_label.setText(str(bpm))

    def set_status(self, status: str):
        # status label removed; ignore status updates
        pass

    def close_overlay(self):
        self.hide()
        self.closed.emit()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            g = event.globalPosition().toPoint()
            r = self.rect()
            margin = 20
            pos = event.pos()
            if (r.right() - pos.x() <= margin) and (r.bottom() - pos.y() <= margin):
                self._resizing = True
                self._resize_start = self.size()
                self._mouse_start = g
            else:
                self._drag_pos = g - self.frameGeometry().topLeft()
        event.accept()

    def mouseMoveEvent(self, event):
        g = event.globalPosition().toPoint()
        if self._resizing and self._resize_start is not None and self._mouse_start is not None:
            delta = g - self._mouse_start
            new_w = max(120, self._resize_start.width() + delta.x())
            new_h = max(40, self._resize_start.height() + delta.y())
            self.resize(new_w, new_h)
        elif self._drag_pos is not None:
            try:
                self.move(g - self._drag_pos)
            except Exception:
                pass
        event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        self._resizing = False
        self._resize_start = None
        self._mouse_start = None
        event.accept()


class HeartRateMonitor(QMainWindow):
    def __init__(self, model: Model):
        super().__init__()
        self.model = model
        self.setWindowTitle("ANT+ Heart Rate Monitor")
        # Smaller default size for a minimal display area
        self.setGeometry(100, 100, 220, 120)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        # central widget
        central = QWidget()
        pal = central.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(240, 240, 240))
        central.setPalette(pal)
        central.setAutoFillBackground(True)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.bpm_label = QLabel("--")
        self.bpm_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Slightly smaller font to fit minimal display
        self.bpm_label.setFont(QFont("Arial", 48, QFont.Weight.Bold))
        self.bpm_label.setStyleSheet("color: black; background-color: transparent; padding:6px;")
        layout.addWidget(self.bpm_label)

        # overlay window (top-level, not parented)
        self.overlay = OverlayWindow()
        self.overlay.closed.connect(self._on_overlay_closed)

        # connect model (only BPM updates are used)
        self.model.bpm_changed.connect(self._on_bpm)

        # shortcuts
        sc_o = QShortcut(QKeySequence('O'), self, activated=self.toggle_overlay)
        sc_o.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc_esc = QShortcut(QKeySequence('Esc'), self, activated=self.exit_overlay)
        sc_esc.setContext(Qt.ShortcutContext.ApplicationShortcut)

    def _on_bpm(self, bpm: int):
        self.bpm_label.setText(str(bpm))
        self.overlay.set_bpm(bpm)


    def toggle_overlay(self):
        if self.overlay.isVisible():
            self.overlay.hide()
            # restore main window appearance
            try:
                self.bpm_label.setStyleSheet("color: black; background-color: transparent; padding:6px;")
            except Exception:
                pass
            self.show()
            self.raise_()
        else:
            # show overlay positioned over main
            geom = self.geometry()
            self.overlay.setGeometry(geom)
            self.hide()
            self.overlay.show()
            self.overlay.raise_()

    def _on_overlay_closed(self):
        self.show()
        self.raise_()

    def exit_overlay(self):
        if self.overlay.isVisible():
            self.overlay.hide()
            self.show()

    def closeEvent(self, event):
        self.model.stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    model = Model()
    win = HeartRateMonitor(model)
    win.show()
    model.start()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
