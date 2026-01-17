
import sys
import threading
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QPushButton, QTextEdit, QTableWidget, 
                               QTableWidgetItem, QHeaderView, QTabWidget, QMenu,
                               QLabel, QLineEdit, QMessageBox, QComboBox)
from PySide6.QtCore import Qt, Signal, QObject, Slot, QThread, QTimer
from PySide6.QtGui import QAction, QTextCursor

import main
from utils.cache import Cache

import queue

# Global Queue for logs
log_queue = queue.Queue()

class LogRedirector:
    def write(self, text):
        log_queue.put(text)
        try:
            with open("sync_log.txt", "a", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            pass

    def flush(self):
        pass

class SyncWorker(QThread):
    finished_signal = Signal()
    
    def __init__(self, resync=False):
        super().__init__()
        self.resync = resync

    def run(self):
        try:
            main.start(resync=self.resync)
        except Exception as e:
            print(f"Error in sync: {e}")
        finally:
            self.finished_signal.emit()

class CacheManagerTab(QWidget):
# ... (Keep CacheManagerTab as is)    
    def __init__(self):
        super().__init__()
        self.cache = Cache()
        self.layout = QVBoxLayout(self)
        
        # Search Bar
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))
        self.search_input = QLineEdit()
        
        # Debounce Timer
        self.search_timer = QTimer()
        self.search_timer.setInterval(300)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.perform_filter)
        
        self.search_input.textChanged.connect(lambda: self.search_timer.start())
        search_layout.addWidget(self.search_input)
        self.layout.addLayout(search_layout)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Key/URL", "ID", "Status", "Raw Data"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.layout.addWidget(self.table)
        
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.load_data)
        self.layout.addWidget(self.refresh_btn)

        self.load_data()

    def load_data(self):
        self.table.setRowCount(0)
        # Re-instantiate to get fresh data from disk
        self.cache = Cache()
        items = self.cache.get_all_items()
        
        for url, data in items.items():
            row = self.table.rowCount()
            self.table.insertRow(row)
            
            # Data parsing
            imdb_id = ""
            status = ""
            if isinstance(data, dict):
                imdb_id = data.get('id', '')
                status = data.get('status', '')
            else:
                imdb_id = str(data)
                
            self.table.setItem(row, 0, QTableWidgetItem(url))
            self.table.setItem(row, 1, QTableWidgetItem(imdb_id))
            
            # Status ComboBox
            combo = QComboBox()
            combo.addItems(["", "ignored", "completed"])
            combo.setCurrentText(str(status) if status else "")
            # Using lambda to capture url. Need default arg for late binding fix.
            combo.currentTextChanged.connect(lambda text, u=url: self.update_status_from_combo(u, text))
            self.table.setCellWidget(row, 2, combo)
            
            self.table.setItem(row, 3, QTableWidgetItem(str(data)))

    def update_status_from_combo(self, url, text):
        # Convert "" back to None for logic or keep ""? Cache handles "" as valid status?
        # main.py checks == 'ignored' or 'completed'. "" is fine.
        val = text if text else ""
        self.cache.set_status(url, val)
        # No need to popup success for every combo change.

    def perform_filter(self):
        text = self.search_input.text().lower()
        self.table.setUpdatesEnabled(False)
        for i in range(self.table.rowCount()):
            match = False
            for j in range(self.table.columnCount()):
                item = self.table.item(i, j)
                if item and text in item.text().lower():
                    match = True
                    break
            self.table.setRowHidden(i, not match)
        self.table.setUpdatesEnabled(True)

    def show_context_menu(self, pos):
        menu = QMenu()
        ignore_action = QAction("Mark as Ignored", self)
        completed_action = QAction("Mark as Completed", self)
        clear_action = QAction("Clear Status", self)
        
        ignore_action.triggered.connect(lambda: self.set_status("ignored"))
        completed_action.triggered.connect(lambda: self.set_status("completed"))
        clear_action.triggered.connect(lambda: self.set_status(None))
        
        menu.addAction(ignore_action)
        menu.addAction(completed_action)
        menu.addAction(clear_action)
        
        menu.exec_(self.table.viewport().mapToGlobal(pos))

    def set_status(self, status):
        rows = set(index.row() for index in self.table.selectedIndexes())
        if not rows:
            return
            
        for row in rows:
            url_item = self.table.item(row, 0)
            if not url_item: continue
            url = url_item.text()
            
            # Update Cache
            if status is None:
                self.cache.set_status(url, '')
            else:
                self.cache.set_status(url, status)
                
            # Update UI
            self.table.setItem(row, 2, QTableWidgetItem(str(status) if status else ""))
            
        QMessageBox.information(self, "Success", f"Updated {len(rows)} items.")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TraktSync GUI")
        self.resize(900, 600)
        
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        
        # --- Tab 1: Sync Control ---
        self.sync_tab = QWidget()
        self.sync_layout = QVBoxLayout(self.sync_tab)
        
        # Buttons
        btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("Start Sync")
        self.btn_start.clicked.connect(self.start_sync)
        btn_layout.addWidget(self.btn_start)
        
        self.btn_resync = QPushButton("Force Resync")
        self.btn_resync.setStyleSheet("background-color: #ffcccc;")
        self.btn_resync.clicked.connect(self.force_resync)
        btn_layout.addWidget(self.btn_resync)
        
        self.sync_layout.addLayout(btn_layout)
        
        # Log Output
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("background-color: black; color: white; font-family: Consolas;")
        self.sync_layout.addWidget(self.log_text)
        
        self.tabs.addTab(self.sync_tab, "Sync Control")
        
        # --- Tab 2: Cache Manager ---
        self.cache_tab = CacheManagerTab()
        self.tabs.addTab(self.cache_tab, "Cache Manager")
        
        # --- Logging Setup (Queue Based) ---
        sys.stdout = LogRedirector()
        # Ensure stderr is safe
        sys.stderr = sys.__stdout__ # Redirect stderr to same logger

        # Log Polling Timer
        self.log_timer = QTimer()
        self.log_timer.setInterval(100) # Check every 100ms
        self.log_timer.timeout.connect(self.process_logs)
        self.log_timer.start()

        self.worker = None

    def process_logs(self):
        while not log_queue.empty():
            try:
                text = log_queue.get_nowait()
                self.log_text.moveCursor(QTextCursor.End)
                self.log_text.insertPlainText(text)
                self.log_text.ensureCursorVisible()
            except queue.Empty:
                break

    def start_sync(self):
        self.run_worker(resync=False)

    def force_resync(self):
        reply = QMessageBox.question(self, 'Confirm Resync', 
                                     "Force Resync will remove history from Trakt before adding (except preserved advanced progress). Are you sure?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.run_worker(resync=True)

    def run_worker(self, resync):
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Running", "Sync is already running!")
            return
            
        self.btn_start.setEnabled(False)
        self.btn_resync.setEnabled(False)
        self.log_text.clear()
        
        self.worker = SyncWorker(resync)
        self.worker.finished_signal.connect(self.on_worker_finished)
        self.worker.start()

    def on_worker_finished(self):
        self.btn_start.setEnabled(True)
        self.btn_resync.setEnabled(True)
        QMessageBox.information(self, "Done", "Sync process finished.")
        # Refresh cache tab in case it changed
        self.cache_tab.load_data()

def main_gui():
    # Clear log file on startup
    with open("sync_log.txt", "w", encoding="utf-8") as f:
        f.write("")
        
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main_gui()
