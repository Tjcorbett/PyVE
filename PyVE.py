import sys
import re
import os
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QLabel,
                             QMessageBox, QProgressBar, QTabWidget, QPushButton,
                             QHBoxLayout, QListWidget, QSpacerItem, QSizePolicy,
                             QListWidgetItem, QTabBar)
from PyQt5.QtGui import QPalette, QColor, QFont, QBrush
from PyQt5.QtCore import Qt, QTimer, QPoint
from proxmoxer import ResourceException, ProxmoxAPI
import logging

# Configuration (use environment variables for security)
PROXMOX_HOST = os.getenv('PROXMOX_HOST', 'your_proxmox_ip')
PROXMOX_PORT = int(os.getenv('PROXMOX_PORT', 8006))
PROXMOX_USER = os.getenv('PROXMOX_USER', 'your_user') #Example User: root@pam
PROXMOX_PASSWORD = os.getenv('PROXMOX_PASSWORD', 'your_password')
PROXMOX_NODE = os.getenv('PROXMOX_NODE', 'pve')
VERIFY_SSL = os.getenv('PROXMOX_VERIFY_SSL', 'False').lower() == 'true'
UPDATE_INTERVAL_MS = 10000  # Increased to 10 seconds to reduce API load

# Configure logging to console and file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('monitor_app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Global Proxmox connection
proxmox = None
connection_error_details = None

def initialize_proxmox_connection():
    """Initialize connection to Proxmox server with retry logic."""
    global proxmox, connection_error_details
    max_retries = 3
    for attempt in range(max_retries):
        try:
            if not VERIFY_SSL:
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            proxmox = ProxmoxAPI(PROXMOX_HOST, port=PROXMOX_PORT, user=PROXMOX_USER,
                                 password=PROXMOX_PASSWORD, verify_ssl=VERIFY_SSL, timeout=10)
            proxmox.version.get()  # Test connection
            logger.info(f"Connected to Proxmox host {PROXMOX_HOST} on node {PROXMOX_NODE}")
            return True
        except Exception as e:
            connection_error_details = f"Proxmox connection error (attempt {attempt + 1}/{max_retries}): {e}"
            logger.error(connection_error_details)
            if attempt < max_retries - 1:
                import time
                time.sleep(2)  # Wait before retrying
    return False

class ScrollableTabBar(QTabBar):
    """Custom QTabBar with mouse/touch drag scrolling."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setUsesScrollButtons(True)
        self._drag_start_pos = None
        self._scroll_offset = 0
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start_pos is not None:
            delta = event.pos().x() - self._drag_start_pos.x()
            self._scroll_offset -= delta
            self._drag_start_pos = event.pos()
            self.update_scroll_position()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)

    def update_scroll_position(self):
        total_width = sum(self.tabRect(i).width() for i in range(self.count()))
        visible_width = self.width()

        if total_width <= visible_width:
            self._scroll_offset = 0
        else:
            max_offset = total_width - visible_width
            self._scroll_offset = max(0, min(self._scroll_offset, max_offset))

        self.update()  # Changed from repaint() to reduce flickering

class MonitorApp(QWidget):
    """Main application window for Proxmox monitoring and management."""
    
    def __init__(self):
        super().__init__()
        self.set_dark_theme()
        self.init_ui()
        self.setup_update_timer()

    def set_dark_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(45, 45, 45))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Base, QColor(35, 35, 35))
        palette.setColor(QPalette.Button, QColor(65, 65, 65))
        palette.setColor(QPalette.ButtonText, Qt.white)
        palette.setColor(QPalette.Text, Qt.white)
        palette.setColor(QPalette.Highlight, QColor(85, 85, 85))
        palette.setColor(QPalette.HighlightedText, Qt.white)
        self.setPalette(palette)
        app = QApplication.instance()
        if app:
            app.setPalette(palette)

    def init_ui(self):
        self.setWindowTitle("PyVE Manager")
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setStyleSheet(self.get_stylesheet())
        
        # Main layout
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # Tab widget with custom scrollable tab bar
        self.tabs = QTabWidget()
        self.tabs.setTabBar(ScrollableTabBar())
        self.tabs.setMovable(False)
        self.tabs.setTabsClosable(False)

        self.pyve_tab = QWidget()
        self.vm_tab = QWidget()
        self.container_tab = QWidget()
        self.exit_tab = QWidget()

        self.tabs.addTab(self.pyve_tab, "PyVE")
        self.tabs.addTab(self.vm_tab, "VMs")
        self.tabs.addTab(self.container_tab, "CTs")
        self.exit_tab_index = self.tabs.addTab(self.exit_tab, "Exit")

        self.tabs.currentChanged.connect(self.on_tab_changed)

        main_layout.addWidget(self.tabs)
        self.setLayout(main_layout)

        # Initialize tab contents
        self.vm_list = QListWidget()
        self.container_list = QListWidget()
        self.init_pyve_tab()
        self.init_vm_tab()
        self.init_container_tab()

    def get_stylesheet(self):
        return """
            QWidget { font-size: 14pt; }
            QPushButton { 
                padding: 6px; border: 1px solid #555; border-radius: 4px; 
                min-width: 100px; min-height: 40px; font-size: 14pt; color: white;
            }
            QPushButton:hover { border-color: #777; }
            QPushButton:pressed { border-color: #999; }
            QPushButton#startButton { 
                background-color: #4CAF50; color: black; font-weight: bold;
            }
            QPushButton#startButton:hover { background-color: #66BB6A; }
            QPushButton#startButton:pressed { background-color: #388E3C; }
            QPushButton#stopButton { 
                background-color: #F44336; color: black; font-weight: bold;
            }
            QPushButton#stopButton:hover { background-color: #EF5350; }
            QPushButton#stopButton:pressed { background-color: #D32F2F; }
            QPushButton#rebootButton { 
                background-color: #FFEB3B; color: black; font-weight: bold;
            }
            QPushButton#rebootButton:hover { background-color: #FFF176; }
            QPushButton#rebootButton:pressed { background-color: #FBC02D; }
            QPushButton#shutdownButton { 
                background-color: #FF9800; color: black; font-weight: bold;
            }
            QPushButton#shutdownButton:hover { background-color: #FFA726; }
            QPushButton#shutdownButton:pressed { background-color: #F57C00; }
            QListWidget { 
                border: 1px solid #4a4a4a; border-radius: 4px; font-size: 16pt; font-weight: bold;
            }
            QListWidget::item { height: 60px; }
            QTabWidget::pane { 
                border: 1px solid #4a4a4a; background-color: #353535; 
            }
            QTabBar::tab { 
                background-color: #505050; color: white; padding: 8px 16px;
                border: 1px solid #4a4a4a; border-bottom: none; 
                border-top-left-radius: 4px; border-top-right-radius: 4px; 
                font-size: 14pt; min-width: 80px; min-height: 32px; font-weight: bold;
            }
            QTabBar::tab:selected { 
                background-color: #42a5f5; color: white; border-bottom: 1px solid #42a5f5; 
            }
            QTabBar::tab:!selected:hover { background-color: #5e5e5e; }
            QTabBar::tab:last { 
                background-color: #505050; 
            }
            QTabBar::tab:last:selected { 
                background-color: #F44336;
            }
            QTabBar::tab:last:!selected:hover { 
                background-color: #EF5350;
            }
            QTabBar::scroller { 
                width: 80px; 
            }
            QTabBar::left-arrow, QTabBar::right-arrow { 
                width: 48px; height: 48px; background: #505050; 
                border: 1px solid #4a4a4a; border-radius: 4px; 
            }
            QTabBar::left-arrow:hover, QTabBar::right-arrow:hover { 
                background: #5e5e5e; 
            }
            QTabBar::left-arrow:pressed, QTabBar::right-arrow:pressed { 
                background: #777; 
            }
            QLabel { background-color: transparent; font-size: 14pt; }
            QProgressBar { 
                border: 1px solid grey; border-radius: 4px; text-align: center; 
                background-color: #3a3a3a; height: 36px; font-size: 12pt;
            }
            QProgressBar::chunk { border-radius: 4px; }
            #CpuBar::chunk { background-color: #42a5f5; }
            #RamBar::chunk { background-color: #ef5350; }
            #DiskBar::chunk { background-color: #66bb6a; }
            #IoDelayBar::chunk { background-color: #ffca28; }
        """

    def setup_update_timer(self):
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_stats)
        self.update_timer.start(UPDATE_INTERVAL_MS)
        QTimer.singleShot(150, self.update_stats)

    def on_tab_changed(self, index):
        if index == self.exit_tab_index:
            QApplication.quit()

    def init_pyve_tab(self):
        layout = QVBoxLayout(self.pyve_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Fixed))

        stats_font = QFont()
        stats_font.setPointSize(14)
        stats_font.setBold(True)

        initial_state = "Connecting..." if proxmox else "Error"
        initial_cores_threads = "Fetching..." if proxmox else "N/A"
        enabled = bool(proxmox)

        self.pyve_cpu_label = QLabel(f'CPU ({initial_cores_threads})')
        self.pyve_cpu_label.setFont(stats_font)
        self.pyve_cpu_bar = QProgressBar()
        self.pyve_cpu_bar.setObjectName("CpuBar")
        self.pyve_cpu_bar.setTextVisible(True)
        self.pyve_cpu_bar.setFormat("%p%")
        self.pyve_cpu_bar.setValue(0)
        self.pyve_cpu_bar.setEnabled(enabled)
        layout.addWidget(self.pyve_cpu_label)
        layout.addWidget(self.pyve_cpu_bar)

        self.pyve_ram_label = QLabel(f'RAM: {initial_state}')
        self.pyve_ram_label.setFont(stats_font)
        self.pyve_ram_bar = QProgressBar()
        self.pyve_ram_bar.setObjectName("RamBar")
        self.pyve_ram_bar.setTextVisible(True)
        self.pyve_ram_bar.setFormat("%p%")
        self.pyve_ram_bar.setValue(0)
        self.pyve_ram_bar.setEnabled(enabled)
        layout.addWidget(self.pyve_ram_label)
        layout.addWidget(self.pyve_ram_bar)

        self.pyve_disk_label = QLabel(f'Disk: {initial_state}')
        self.pyve_disk_label.setFont(stats_font)
        self.pyve_disk_bar = QProgressBar()
        self.pyve_disk_bar.setObjectName("DiskBar")
        self.pyve_disk_bar.setTextVisible(True)
        self.pyve_disk_bar.setFormat("%p%")
        self.pyve_disk_bar.setValue(0)
        self.pyve_disk_bar.setEnabled(enabled)
        layout.addWidget(self.pyve_disk_label)
        layout.addWidget(self.pyve_disk_bar)

        self.pyve_iodelay_label = QLabel(f'I/O Delay: {initial_state}')
        self.pyve_iodelay_label.setFont(stats_font)
        self.pyve_iodelay_bar = QProgressBar()
        self.pyve_iodelay_bar.setObjectName("IoDelayBar")
        self.pyve_iodelay_bar.setTextVisible(True)
        self.pyve_iodelay_bar.setFormat("%p%")
        self.pyve_iodelay_bar.setValue(0)
        self.pyve_iodelay_bar.setEnabled(enabled)
        layout.addWidget(self.pyve_iodelay_label)
        layout.addWidget(self.pyve_iodelay_bar)

        layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding))

        if not proxmox:
            self.set_error_state()

    def set_error_state(self):
        self.pyve_cpu_label.setText("CPU (N/A)")
        self.pyve_ram_label.setText("RAM: Error")
        self.pyve_disk_label.setText("Disk: Error")
        self.pyve_iodelay_label.setText("I/O Delay: Error")

    def init_vm_tab(self):
        layout = QVBoxLayout(self.vm_tab)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        self.vm_list.setWordWrap(True)
        layout.addWidget(self.vm_list)

        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(8)
        
        self.vm_start_button = QPushButton('Start')
        self.vm_start_button.setObjectName("startButton")
        self.vm_stop_button = QPushButton('Stop')
        self.vm_stop_button.setObjectName("stopButton")
        self.vm_restart_button = QPushButton('Reboot')
        self.vm_restart_button.setObjectName("rebootButton")
        self.vm_shutdown_button = QPushButton('Shutdown')
        self.vm_shutdown_button.setObjectName("shutdownButton")

        for btn in (self.vm_start_button, self.vm_stop_button, 
                   self.vm_restart_button, self.vm_shutdown_button):
            buttons_layout.addWidget(btn)
        layout.addLayout(buttons_layout)

        self.vm_start_button.clicked.connect(self.start_vm)
        self.vm_stop_button.clicked.connect(self.stop_vm)
        self.vm_restart_button.clicked.connect(self.reboot_vm)
        self.vm_shutdown_button.clicked.connect(self.shutdown_vm)

        # Disable buttons when no item is selected
        self.vm_list.itemSelectionChanged.connect(self.update_vm_button_state)
        self.update_vm_button_state()

    def init_container_tab(self):
        layout = QVBoxLayout(self.container_tab)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        self.container_list.setWordWrap(True)
        layout.addWidget(self.container_list)

        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(8)
        
        self.container_start_button = QPushButton('Start')
        self.container_start_button.setObjectName("startButton")
        self.container_stop_button = QPushButton('Stop')
        self.container_stop_button.setObjectName("stopButton")
        self.container_restart_button = QPushButton('Reboot')
        self.container_restart_button.setObjectName("rebootButton")
        self.container_shutdown_button = QPushButton('Shutdown')
        self.container_shutdown_button.setObjectName("shutdownButton")

        for btn in (self.container_start_button, self.container_stop_button,
                   self.container_restart_button, self.container_shutdown_button):
            buttons_layout.addWidget(btn)
        layout.addLayout(buttons_layout)

        self.container_start_button.clicked.connect(self.start_container)
        self.container_stop_button.clicked.connect(self.stop_container)
        self.container_restart_button.clicked.connect(self.reboot_container)
        self.container_shutdown_button.clicked.connect(self.shutdown_container)

        # Disable buttons when no item is selected
        self.container_list.itemSelectionChanged.connect(self.update_container_button_state)
        self.update_container_button_state()

    def update_vm_button_state(self):
        """Enable/disable VM buttons based on selection."""
        enabled = bool(self.vm_list.selectedItems())
        for btn in (self.vm_start_button, self.vm_stop_button, 
                   self.vm_restart_button, self.vm_shutdown_button):
            btn.setEnabled(enabled)

    def update_container_button_state(self):
        """Enable/disable container buttons based on selection."""
        enabled = bool(self.container_list.selectedItems())
        for btn in (self.container_start_button, self.container_stop_button,
                   self.container_restart_button, self.container_shutdown_button):
            btn.setEnabled(enabled)

    def update_stats(self):
        if not proxmox:
            self.set_error_state()
            self.vm_list.clear()
            self.vm_list.addItem("Disconnected")
            self.container_list.clear()
            self.container_list.addItem("Disconnected")
            return

        try:
            node = proxmox.nodes(PROXMOX_NODE)
            status = node.status.get()

            cpu_percent = status.get('cpu', 0.0) * 100
            cpu_info = status.get('cpuinfo', {})
            cores = cpu_info.get('cores', '?')
            threads = cpu_info.get('cpus', '?')
            self.pyve_cpu_label.setText(f'CPU ({cores} cores, {threads} threads)')
            self.pyve_cpu_bar.setValue(int(cpu_percent))

            ram_used = status.get('memory', {}).get('used', 0) / (1024**3)
            ram_total = status.get('memory', {}).get('total', 1) / (1024**3)
            ram_percent = (ram_used / ram_total) * 100 if ram_total > 0 else 0
            self.pyve_ram_label.setText(f'RAM ({ram_used:.1f}/{ram_total:.1f} GiB)')
            self.pyve_ram_bar.setValue(int(ram_percent))

            disk_used = status.get('rootfs', {}).get('used', 0) / (1024**3)
            disk_total = status.get('rootfs', {}).get('total', 1) / (1024**3)
            disk_percent = (disk_used / disk_total) * 100 if disk_total > 0 else 0
            self.pyve_disk_label.setText(f'Disk ({disk_used:.1f}/{disk_total:.1f} GiB)')
            self.pyve_disk_bar.setValue(int(disk_percent))

            io_delay = status.get('wait', 0.0) * 100
            self.pyve_iodelay_label.setText('I/O Delay')
            self.pyve_iodelay_bar.setFormat(f"{io_delay:.1f}%")
            self.pyve_iodelay_bar.setValue(int(io_delay))

            vms = node.qemu.get()
            self.vm_list.clear()
            for vm in sorted(vms, key=lambda x: x.get('vmid', 0)):
                item_text = f"ID: {vm.get('vmid')} | {vm.get('name')} | {vm.get('status')}"
                item = QListWidgetItem(item_text)
                if vm.get('status') == "running":
                    item.setBackground(QBrush(QColor("#4CAF50")))
                    item.setForeground(QBrush(QColor("black")))
                elif vm.get('status') == "stopped":
                    item.setBackground(QBrush(QColor("#F44336")))
                    item.setForeground(QBrush(QColor("white")))
                self.vm_list.addItem(item)

            containers = node.lxc.get()
            self.container_list.clear()
            for ct in sorted(containers, key=lambda x: x.get('vmid', 0)):
                item_text = f"ID: {ct.get('vmid')} | {ct.get('name')} | {ct.get('status')}"
                item = QListWidgetItem(item_text)
                if ct.get('status') == "running":
                    item.setBackground(QBrush(QColor("#4CAF50")))
                    item.setForeground(QBrush(QColor("black")))
                elif ct.get('status') == "stopped":
                    item.setBackground(QBrush(QColor("#F44336")))
                    item.setForeground(QBrush(QColor("white")))
                self.container_list.addItem(item)
        except ResourceException as e:
            logger.error(f"Proxmox API error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error in update_stats: {e}")

    def _get_selected_vmid(self, list_widget, item_type):
        selected = list_widget.selectedItems()
        if not selected:
            QMessageBox.warning(self, "Selection", f"Select a {item_type} first.")
            return None
        match = re.search(r'ID:\s*(\d+)', selected[0].text())
        return int(match.group(1)) if match else None

    def _perform_action(self, vmid, action_type, resource_type):
        if vmid is None or not proxmox:
            return
        actions = {'start': 'start', 'stop': 'stop', 'reboot': 'reboot', 'shutdown': 'shutdown'}
        try:
            resource = (proxmox.nodes(PROXMOX_NODE).qemu(vmid) if resource_type == 'vm' 
                       else proxmox.nodes(PROXMOX_NODE).lxc(vmid))
            getattr(resource.status, actions[action_type]).post()
            QTimer.singleShot(2000, self.update_stats)
        except ResourceException as e:
            QMessageBox.critical(self, "Error", f"Action failed: {e}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Unexpected error: {e}")

    def start_vm(self): self._perform_action(self._get_selected_vmid(self.vm_list, "VM"), 'start', 'vm')
    def stop_vm(self): self._perform_action(self._get_selected_vmid(self.vm_list, "VM"), 'stop', 'vm')
    def reboot_vm(self): self._perform_action(self._get_selected_vmid(self.vm_list, "VM"), 'reboot', 'vm')
    def shutdown_vm(self): self._perform_action(self._get_selected_vmid(self.vm_list, "VM"), 'shutdown', 'vm')

    def start_container(self): self._perform_action(self._get_selected_vmid(self.container_list, "CT"), 'start', 'container')
    def stop_container(self): self._perform_action(self._get_selected_vmid(self.container_list, "CT"), 'stop', 'container')
    def reboot_container(self): self._perform_action(self._get_selected_vmid(self.container_list, "CT"), 'reboot', 'container')
    def shutdown_container(self): self._perform_action(self._get_selected_vmid(self.container_list, "CT"), 'shutdown', 'container')

if __name__ == '__main__':
    app = QApplication(sys.argv)
    if not initialize_proxmox_connection():
        retry = QMessageBox.question(None, "Connection Error",
                                     f"{connection_error_details}\nRetry connection?",
                                     QMessageBox.Yes | QMessageBox.No)
        if retry == QMessageBox.Yes:
            if initialize_proxmox_connection():
                monitor = MonitorApp()
                monitor.setFixedSize(480, 800)  # Enforce 480x800 resolution
                monitor.show()
                sys.exit(app.exec_())
        sys.exit(1)
    monitor = MonitorApp()
    monitor.setFixedSize(480, 800)  # Enforce 480x800 resolution
    monitor.show()
    sys.exit(app.exec_())