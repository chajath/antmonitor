#!/usr/bin/env python3
"""Simple ANT+ Heart Rate Monitor"""
import sys
import logging
import threading
import platform
from ctypes import c_void_p
from PyQt6.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QKeySequence, QShortcut

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

try:
    from openant.easy.node import Node
    from openant.devices.heart_rate import HeartRate
except ImportError:
    print("Error: openant not installed. Run: pip install openant")
    sys.exit(1)


class SafeHeartRate(HeartRate):
    """HeartRate wrapper that handles Error 21 gracefully"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not hasattr(self, '_attached'):
            self._attached = False
        logger.info("SafeHeartRate initialized")
    
    def _on_data(self, data):
        logger.info(f"_on_data called with {len(data)} bytes: {list(data)}")
        try:
            super()._on_data(data)
            logger.debug("Parent _on_data processed successfully")
        except Exception as e:
            logger.warning(f"Exception in _on_data: {e}")
            if "CHANNEL_IN_WRONG_STATE" in str(e) or "error 21" in str(e):
                logger.info("Handling Error 21 - channel reconfiguration issue")
                # Handle device attachment without reconfiguring channel
                if len(data) > 8 and not self._attached:
                    self.device_id = data[9] + (data[10] << 8)
                    self.trans_type = data[12]
                    self._attached = True
                    logger.info(f"Attached to device_id={self.device_id}")
                # Parse and trigger callbacks manually
                try:
                    # Call parent's on_data to parse the heart rate
                    self.on_data(data)
                    # Trigger device_data callback if it exists
                    if hasattr(self, 'on_device_data') and self.on_device_data:
                        # Heart rate is in byte 7 of the data
                        if len(data) >= 8:
                            from openant.devices.heart_rate import HeartRateData
                            hr_data = HeartRateData()
                            hr_data.heart_rate = data[7]
                            hr_data.beat_time = int.from_bytes(data[4:6], byteorder="little") / 1024
                            hr_data.beat_count = data[6]
                            logger.info(f"Manual callback: BPM={hr_data.heart_rate}")
                            self.on_device_data(data[0], "heart_rate", hr_data)
                except Exception as inner_e:
                    logger.error(f"Error in manual callback: {inner_e}")
            else:
                raise


class AntWorker(QThread):
    """Background thread for ANT+ communication"""
    bpm_update = pyqtSignal(int)
    status_update = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.running = True
        self.node = None
        self.node_thread = None
        logger.info("AntWorker thread created")

    def run(self):
        self.status_update.emit("Connecting to ANT+...")
        logger.info("Starting ANT+ communication thread")
        
        try:
            # Initialize ANT+ node
            logger.info("Initializing ANT node...")
            self.node = Node()
            self.node.set_network_key(0x00, [0xB9, 0xA5, 0x21, 0xFB, 0xBD, 0x72, 0xC3, 0x45])
            
            self.status_update.emit("Searching for heart rate sensor...")
            
            # Create heart rate device with specific ID (42687 found by scan)
            # Using device_id=0 causes Error 21, so use the actual device
            # trans_type from scan: 209 (but we use 0 for pairing mode to accept any)
            logger.info("Creating heart rate device (device_id=42687, trans_type=209)...")
            hr_sensor = SafeHeartRate(self.node, device_id=42687, trans_type=209)
            
            # Set up callback for heart rate data
            def on_found():
                logger.info("Heart rate sensor found!")
                self.status_update.emit("Heart rate sensor found!")
            
            def on_device_data(page, page_name, data):
                """Called when heart rate data page is received"""
                logger.info(f"on_device_data callback: page={page}, page_name={page_name}")
                try:
                    bpm = data.heart_rate
                    logger.info(f"Extracted BPM: {bpm}")
                    if bpm > 0:
                        logger.info(f"Emitting BPM signal: {bpm}")
                        self.bpm_update.emit(bpm)
                        self.status_update.emit("Connected")
                    else:
                        logger.warning("BPM value is 0 or None")
                except Exception as e:
                    logger.error(f"Error in on_device_data: {e}")
            
            def on_heartbeat(event_time):
                """Called on ANT heartbeat"""
                logger.debug(f"ANT heartbeat at {event_time}")
            
            hr_sensor.on_found = on_found
            hr_sensor.on_device_data = on_device_data
            hr_sensor.on_heartbeat = on_heartbeat
            
            # Start the node in a separate daemon thread to avoid blocking
            logger.info("Starting ANT node in background thread...")
            def run_node():
                try:
                    self.node.start()
                except Exception as e:
                    logger.error(f"Node thread error: {e}")
            
            self.node_thread = threading.Thread(target=run_node, daemon=True)
            self.node_thread.start()
            logger.info("ANT node thread started")
            
            # Keep this thread alive but responsive
            while self.running:
                self.msleep(100)  # Sleep for 100ms to keep thread responsive
            
        except Exception as e:
            logger.error(f"Error in ANT worker: {e}")
            self.status_update.emit(f"Error: {str(e)}")
    
    def stop(self):
        logger.info("Stopping ANT worker")
        self.running = False
        if self.node:
            try:
                self.node.stop()
            except:
                pass
        self.quit()
        self.wait()


class HeartRateMonitor(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ANT+ Heart Rate Monitor")
        self.setGeometry(100, 100, 400, 200)
        
        # Always on top and overlay mode state
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.overlay_mode = False
        
        # For window dragging
        self.drag_position = None
        
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # Status label
        self.status_label = QLabel("Initializing...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)
        
        # BPM display
        self.bpm_label = QLabel("--")
        self.bpm_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bpm_label.setFont(QFont("Arial", 72, QFont.Weight.Bold))
        layout.addWidget(self.bpm_label)
        
        # Start ANT+ worker thread
        self.worker = AntWorker()
        self.worker.bpm_update.connect(self.update_bpm)
        self.worker.status_update.connect(self.update_status)
        self.worker.start()
        
        # Keyboard shortcut for overlay mode (O key)
        self.overlay_shortcut = QShortcut(QKeySequence('O'), self)
        self.overlay_shortcut.activated.connect(self.toggle_overlay_mode)
        
        # Escape key to exit overlay mode
        self.escape_shortcut = QShortcut(QKeySequence('Esc'), self)
        self.escape_shortcut.activated.connect(self.exit_overlay_mode)
    
    def update_bpm(self, bpm):
        """Update BPM display"""
        logger.info(f"GUI: Updating BPM display to {bpm}")
        self.bpm_label.setText(str(bpm))
    
    def update_status(self, status):
        """Update status message"""
        logger.debug(f"GUI: Updating status to {status}")
        self.status_label.setText(status)
    
    def toggle_overlay_mode(self):
        """Toggle transparent overlay mode"""
        self.overlay_mode = not self.overlay_mode
        
        if self.overlay_mode:
            # Enable overlay mode
            logger.info("Enabling overlay mode")
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint | 
                Qt.WindowType.WindowStaysOnTopHint |
                Qt.WindowType.Tool
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            
            # Raise to top level
            self.raise_()
            
            # Make window appear on all desktops/spaces (macOS)
            if platform.system() == 'Darwin':
                try:
                    import objc
                    from Cocoa import NSWindow, NSWindowCollectionBehaviorCanJoinAllSpaces, NSStatusWindowLevel
                    
                    ns_view = objc.objc_object(c_void_p=int(self.winId()))
                    ns_window = ns_view.window()
                    
                    # Make window visible on all spaces
                    ns_window.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces)
                    # Use status window level (menu bar level) to stay above Mission Control
                    ns_window.setLevel_(NSStatusWindowLevel)
                except Exception as e:
                    logger.warning(f"Could not set macOS window properties: {e}")
            
            # Style for overlay mode
            self.setStyleSheet("""
                QMainWindow {
                    background-color: rgba(0, 0, 0, 180);
                }
                QLabel {
                    color: rgba(255, 255, 255, 230);
                    background-color: transparent;
                }
            """)
            self.status_label.hide()  # Hide status in overlay mode
            
        else:
            # Disable overlay mode
            logger.info("Disabling overlay mode")
            self.setWindowFlags(
                Qt.WindowType.Window |
                Qt.WindowType.WindowStaysOnTopHint
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
            
            # Reset to normal style
            self.setStyleSheet("")
            self.status_label.show()
        
        self.show()  # Need to show again after changing window flags
    
    def exit_overlay_mode(self):
        """Exit overlay mode if active"""
        if self.overlay_mode:
            self.toggle_overlay_mode()
    
    def mousePressEvent(self, event):
        """Start dragging the window"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event):
        """Drag the window"""
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_position is not None:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
    
    def mouseReleaseEvent(self, event):
        """Stop dragging"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = None
            event.accept()
    
    def closeEvent(self, event):
        """Clean shutdown when window closes"""
        logger.info("Closing application...")
        if hasattr(self, 'worker'):
            self.worker.stop()
            self.worker.wait()
        QApplication.quit()
        event.accept()


def main():
    """Entry point for the application"""
    app = QApplication(sys.argv)
    window = HeartRateMonitor()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
