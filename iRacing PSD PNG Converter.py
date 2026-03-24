from worker import render_preview_worker
import multiprocessing
multiprocessing.freeze_support()
multiprocessing.set_start_method("spawn", force=True)

import sys
import io
import os
from pathlib import Path
from typing import List, Tuple, Dict

from psd_tools import PSDImage
from psd_tools.api.layers import Group
from PIL import Image

from PySide6.QtCore import (
    Qt,
    QTimer,
    QObject,
    Signal,
    Slot,
    QEasingCurve,
    QPropertyAnimation,
)
from PySide6.QtGui import (
    QPixmap,
    QAction,
    QIcon,
)
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFileDialog,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
    QGraphicsOpacityEffect,
    QSplashScreen,
    QDialog,
)

from concurrent.futures import ProcessPoolExecutor, Future


PREVIEW_SCALE = 0.5
DEBOUNCE_MS = 150
FADE_UP_MS = 500
MAX_WORKERS = 4




# ---------- QT HELPERS ----------

class LayerTreeItem(QTreeWidgetItem):
    def __init__(self, psd_layer, path: Tuple[int, ...], *args):
        super().__init__(*args)
        self.psd_layer = psd_layer
        self.layer_path = path


class ResultEmitter(QObject):
    preview_ready = Signal(QPixmap, int)


# ---------- PREMIUM ABOUT DIALOG (CINEMATIC OVERLAY, NO BOX BEHIND LOGOS) ----------

class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Frameless, translucent overlay
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.Dialog
            | Qt.WindowSystemMenuHint
            | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)

        # Full overlay layout
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setAlignment(Qt.AlignCenter)

        # Inner content widget (no box behind logos, just layout)
        content = QWidget(self)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 24, 24, 24)
        content_layout.setSpacing(10)
        content_layout.setAlignment(Qt.AlignCenter)

        # Title
        title_label = QLabel("About")
        title_label.setStyleSheet("color: white; font-size: 20px; font-weight: bold;")
        title_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(title_label)

        # Logos stacked
        logos_layout = QVBoxLayout()
        logos_layout.setAlignment(Qt.AlignCenter)
        logos_layout.setSpacing(8)

        logo1_path = os.path.join(os.path.dirname(__file__), "assets", "logo.png")
        logo2_path = os.path.join(os.path.dirname(__file__), "assets", "logo2.png")

        target_size = 150

        logo1_pix = QPixmap(logo1_path).scaled(
            target_size, target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        logo2_pix = QPixmap(logo2_path).scaled(
            target_size, target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )

        self.logo1_label = QLabel()
        self.logo1_label.setAlignment(Qt.AlignCenter)
        self.logo1_label.setPixmap(logo1_pix)

        self.logo2_label = QLabel()
        self.logo2_label.setAlignment(Qt.AlignCenter)
        self.logo2_label.setPixmap(logo2_pix)

        logos_layout.addWidget(self.logo1_label)
        logos_layout.addWidget(self.logo2_label)

        content_layout.addLayout(logos_layout)

        # Text with clickable YouTube link
        about_label = QLabel()
        about_label.setTextFormat(Qt.RichText)
        about_label.setOpenExternalLinks(True)
        about_label.setAlignment(Qt.AlignCenter)
        about_label.setWordWrap(True)
        about_label.setStyleSheet("color: #DDDDDD; font-size: 12px;")

        about_text = (
            "<h3>iRacing PSD → PNG Converter V1.0</h3>"
            "<p>Created by: <b>Arran McDonald</b></p>"
            "<p>YouTube: "
            "<a href='https://www.youtube.com/@arranmc182'>@arranmc182</a></p>"
            "<p>This program uses:<br>"
            "psd-tools · Pillow · PySide6 · Python multiprocessing</p>"
            "<p><i></i></p>"
        )
        about_label.setText(about_text)

        content_layout.addWidget(about_label)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(
            "QPushButton {"
            "  color: white;"
            "  background-color: #444444;"
            "  border-radius: 6px;"
            "  padding: 6px 14px;"
            "}"
            "QPushButton:hover {"
            "  background-color: #666666;"
            "}"
        )
        close_btn.clicked.connect(self.accept)
        content_layout.addWidget(close_btn, alignment=Qt.AlignCenter)

        outer_layout.addWidget(content)

        # Semi-transparent dark overlay background
        self.setStyleSheet(
            "QDialog { background-color: rgba(0, 0, 0, 160); }"
        )

        # Fade-in animation for whole window
        self.setWindowOpacity(0.0)
        self.fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self.fade_anim.setDuration(300)
        self.fade_anim.setStartValue(0.0)
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.setEasingCurve(QEasingCurve.InOutQuad)

    def showEvent(self, event):
        super().showEvent(event)
        # Center on parent
        parent = self.parent() or self.window()
        if parent is not None:
            pr = parent.frameGeometry()
            self.resize(460, 480)
            self.move(
                pr.center().x() - self.width() // 2,
                pr.center().y() - self.height() // 2,
            )
        else:
            self.resize(460, 480)
        self.fade_anim.start()


# ---------- MAIN WINDOW ----------

class PSDToPNGWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        icon_path = os.path.join(os.path.dirname(__file__), "assets", "logo.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.setWindowTitle("iRacing PSD → PNG Converter")
        self.resize(1400, 800)

        self.current_psd_path: Path | None = None
        self.psd: PSDImage | None = None
        self.current_composite_pixmap: QPixmap | None = None

        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(DEBOUNCE_MS)
        self.preview_timer.timeout.connect(self._start_preview_render)

        self.executor = ProcessPoolExecutor(max_workers=MAX_WORKERS)
        self.current_job_id = 0
        self.future_job_ids: Dict[Future, int] = {}
        self.result_emitter = ResultEmitter()
        self.result_emitter.preview_ready.connect(self._on_render_finished)

        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # LEFT PANEL
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        self.psd_label = QLabel("No PSD loaded")
        self.psd_label.setWordWrap(True)

        self.open_psd_button = QPushButton("Open PSD Template")
        self.open_psd_button.clicked.connect(self.open_psd)

        self.export_png_button = QPushButton("Export PNG")
        self.export_png_button.setEnabled(False)
        self.export_png_button.clicked.connect(self.export_png)

        self.layer_tree = QTreeWidget()
        self.layer_tree.setHeaderLabels(["Layers"])
        self.layer_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.layer_tree.itemChanged.connect(self.on_layer_item_changed)
        self.layer_tree.setEnabled(False)

        info_label = QLabel(
            "Usage:\n"
            "1. Open an iRacing PSD template\n"
            "2. Toggle layer visibility\n"
            "3. Preview renders at 50% scale using 4 CPU cores\n"
            "4. Export full-res PNG\n"
        )
        info_label.setWordWrap(True)

        left_layout.addWidget(self.psd_label)
        left_layout.addWidget(self.open_psd_button)
        left_layout.addWidget(self.export_png_button)
        left_layout.addWidget(QLabel("Layer visibility:"))
        left_layout.addWidget(self.layer_tree, stretch=1)
        left_layout.addWidget(info_label)
        left_layout.addStretch(0)

        # RIGHT PANEL
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        self.preview_label = QLabel("Preview will appear here after loading a PSD.")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("background-color: #202020; color: #CCCCCC;")

        self.opacity_effect = QGraphicsOpacityEffect(self.preview_label)
        self.preview_label.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(1.0)

        self.fade_anim = QPropertyAnimation(self.opacity_effect, b"opacity", self)
        self.fade_anim.setDuration(FADE_UP_MS)
        self.fade_anim.setStartValue(0.5)
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.setEasingCurve(QEasingCurve.InOutQuad)

        self.loading_overlay = QLabel("Rendering preview…", self.preview_label)
        self.loading_overlay.setAlignment(Qt.AlignCenter)
        self.loading_overlay.setStyleSheet(
            "background-color: rgba(0, 0, 0, 150); color: white; font-size: 24px;"
        )
        self.loading_overlay.hide()

        right_layout.addWidget(self.preview_label)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([400, 1000])

        # MENU: FILE
        file_menu = self.menuBar().addMenu("File")

        open_action = QAction("Open PSD", self)
        open_action.triggered.connect(self.open_psd)
        file_menu.addAction(open_action)

        export_action = QAction("Export PNG", self)
        export_action.triggered.connect(self.export_png)
        file_menu.addAction(export_action)

        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # MENU: HELP
        help_menu = self.menuBar().addMenu("Help")

        instructions_action = QAction("Instructions", self)
        instructions_action.triggered.connect(self.show_instructions)
        help_menu.addAction(instructions_action)

        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    # ---------- HELP / ABOUT ----------

    def show_instructions(self):
        text = (
            "iRacing PSD → PNG Converter Instructions\n\n"
            "1. Open an iRacing PSD template.\n"
            "2. Toggle layer visibility using the tree.\n"
            "3. Preview updates at 50% scale using 4 CPU cores.\n"
            "4. Smooth fade animation during updates.\n"
            "5. Export full-resolution PNG when ready.\n"
            "6. UI stays responsive thanks to multiprocessing.\n"
        )
        dlg = QDialog(self)
        dlg.setWindowTitle("Instructions")
        layout = QVBoxLayout(dlg)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        layout.addWidget(lbl)
        btn = QPushButton("Close")
        btn.clicked.connect(dlg.accept)
        layout.addWidget(btn, alignment=Qt.AlignRight)
        dlg.exec()

    def show_about(self):
        dlg = AboutDialog(self)
        dlg.exec()

    # ---------- PSD + LAYERS ----------

    def open_psd(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open iRacing PSD Template", "", "PSD Files (*.psd)"
        )
        if not file_path:
            return

        try:
            self.psd = PSDImage.open(file_path)
            self.current_psd_path = Path(file_path)

            self.psd_label.setText(f"Loaded PSD:\n{Path(file_path).name}")
            self.export_png_button.setEnabled(True)
            self.layer_tree.setEnabled(True)

            self._populate_layer_tree()
            self._start_preview_render()

        except Exception as e:
            dlg = QDialog(self)
            dlg.setWindowTitle("Error")
            layout = QVBoxLayout(dlg)
            lbl = QLabel(f"Failed to open PSD:\n{e}")
            lbl.setWordWrap(True)
            layout.addWidget(lbl)
            btn = QPushButton("Close")
            btn.clicked.connect(dlg.accept)
            layout.addWidget(btn, alignment=Qt.AlignRight)
            dlg.exec()

    def _populate_layer_tree(self):
        self.layer_tree.blockSignals(True)
        self.layer_tree.clear()

        def add_items(parent_item, layers, parent_path):
            for idx, layer in enumerate(layers):
                name = layer.name or "(unnamed)"
                path = parent_path + (idx,)
                item = LayerTreeItem(layer, path, parent_item)
                item.setText(0, name)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Checked if layer.visible else Qt.Unchecked)

                if isinstance(layer, Group):
                    add_items(item, layer, path)

        for idx, layer in enumerate(self.psd):
            name = layer.name or "(unnamed)"
            path = (idx,)
            item = LayerTreeItem(layer, path)
            item.setText(0, name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if layer.visible else Qt.Unchecked)
            self.layer_tree.addTopLevelItem(item)

            if isinstance(layer, Group):
                add_items(item, layer, path)

        self.layer_tree.expandAll()
        self.layer_tree.blockSignals(False)

    def on_layer_item_changed(self, item, column):
        if column != 0:
            return

        checked = item.checkState(0) == Qt.Checked
        item.psd_layer.visible = checked

        def sync_children(parent_item, visible):
            for i in range(parent_item.childCount()):
                child = parent_item.child(i)
                child.psd_layer.visible = visible
                child.setCheckState(0, Qt.Checked if visible else Qt.Unchecked)
                sync_children(child, visible)

        sync_children(item, checked)
        self.preview_timer.start()

    # ---------- VISIBILITY STATE ----------

    def _collect_visibility_state(self):
        state = []

        def collect(layers, parent_path):
            for idx, layer in enumerate(layers):
                path = parent_path + (idx,)
                state.append((path, layer.visible))
                if isinstance(layer, Group):
                    collect(layer, path)

        collect(self.psd, ())
        return state

    # ---------- PREVIEW RENDERING ----------

    def _start_preview_render(self):
        if self.psd is None:
            return

        self.current_job_id += 1
        job_id = self.current_job_id

        visibility_state = self._collect_visibility_state()

        self.fade_anim.stop()
        self.opacity_effect.setOpacity(0.5)

        self.loading_overlay.resize(self.preview_label.size())
        self.loading_overlay.show()

        future = self.executor.submit(
            render_preview_worker,
            str(self.current_psd_path),
            visibility_state,
            PREVIEW_SCALE,
        )
        self.future_job_ids[future] = job_id
        future.add_done_callback(self._on_future_done)

    def _on_future_done(self, future):
        job_id = self.future_job_ids.pop(future, None)
        if job_id is None:
            return

        try:
            data = future.result()
        except Exception:
            data = b""

        pixmap = QPixmap()
        if data:
            pixmap.loadFromData(data, "PNG")

        self.result_emitter.preview_ready.emit(pixmap, job_id)

    @Slot(QPixmap, int)
    def _on_render_finished(self, pixmap, job_id):
        if job_id != self.current_job_id:
            return

        self.current_composite_pixmap = pixmap
        self._update_preview_label_pixmap()

        self.loading_overlay.hide()

        self.fade_anim.stop()
        self.opacity_effect.setOpacity(0.5)
        self.fade_anim.start()

    def _update_preview_label_pixmap(self):
        if self.current_composite_pixmap is None:
            self.preview_label.setText("Preview will appear here after loading a PSD.")
            self.preview_label.setPixmap(QPixmap())
            return

        self.preview_label.setText("")
        scaled = self.current_composite_pixmap.scaled(
            self.preview_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_preview_label_pixmap()
        self.loading_overlay.resize(self.preview_label.size())

    # ---------- EXPORT ----------

    def export_png(self):
        if self.psd is None:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export PNG", "output.png", "PNG Files (*.png)"
        )
        if not file_path:
            return

        try:
            psd = PSDImage.open(self.current_psd_path)
            vis_state = self._collect_visibility_state()
            vis_map = {p: v for p, v in vis_state}

            def apply_visibility(layers, parent_path):
                for idx, layer in enumerate(layers):
                    path = parent_path + (idx,)
                    if path in vis_map:
                        layer.visible = vis_map[path]
                    if isinstance(layer, Group):
                        apply_visibility(layer, path)

            apply_visibility(psd, ())
            composite = psd.composite()
            composite.save(file_path, "PNG")

            dlg = QDialog(self)
            dlg.setWindowTitle("Export Complete")
            layout = QVBoxLayout(dlg)
            lbl = QLabel(f"Saved:\n{file_path}")
            lbl.setWordWrap(True)
            layout.addWidget(lbl)
            btn = QPushButton("Close")
            btn.clicked.connect(dlg.accept)
            layout.addWidget(btn, alignment=Qt.AlignRight)
            dlg.exec()

        except Exception as e:
            dlg = QDialog(self)
            dlg.setWindowTitle("Error")
            layout = QVBoxLayout(dlg)
            lbl = QLabel(f"Export failed:\n{e}")
            lbl.setWordWrap(True)
            layout.addWidget(lbl)
            btn = QPushButton("Close")
            btn.clicked.connect(dlg.accept)
            layout.addWidget(btn, alignment=Qt.AlignRight)
            dlg.exec()

    def closeEvent(self, event):
        self.executor.shutdown(wait=False)
        super().closeEvent(event)


# ---------- MAIN ----------

def main():
    app = QApplication(sys.argv)

    splash_path = os.path.join(os.path.dirname(__file__), "assets", "logo.png")
    splash_pix = QPixmap(splash_path).scaled(
        300, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation
    )

    splash = QSplashScreen(splash_pix, Qt.WindowStaysOnTopHint)
    splash.show()
    app.processEvents()

    QTimer.singleShot(1500, splash.close)

    window = PSDToPNGWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    multiprocessing.set_start_method("spawn", force=True)
    main()
