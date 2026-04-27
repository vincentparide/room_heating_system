# ui_main.py
import sys, os, json
from PyQt5 import QtCore, QtWidgets, QtGui
from PyQt5.QtWidgets import QDoubleSpinBox, QComboBox, QHBoxLayout, QVBoxLayout, QFormLayout, QGroupBox, QPushButton, QLabel, QSplitter, QScrollArea, QPlainTextEdit
from PIL.ImageQt import ImageQt

# Imports
from models import RoomSpec, TileSpec, SupportSpec, HeatingSpec
from view_gl import GLRoomView
from qr_engine import make_qr
from layout_engine import compute_layout

# DXF Export Function (Inline for simplicity)
def export_dxf(room, tiles, supports, circuit, filepath):
    with open(filepath, "w") as f:
        f.write("0\nSECTION\n2\nENTITIES\n")
        L, W = room.length_m, room.width_m
        # Room outline
        f.write(f"0\nLINE\n8\nROOM\n10\n0\n20\n0\n30\n0\n11\n{L}\n21\n0\n31\n0\n")
        f.write(f"0\nLINE\n8\nROOM\n10\n{L}\n20\n0\n30\n0\n11\n{L}\n21\n{W}\n31\n0\n")
        f.write(f"0\nLINE\n8\nROOM\n10\n{L}\n20\n{W}\n30\n0\n11\n0\n21\n{W}\n31\n0\n")
        f.write(f"0\nLINE\n8\nROOM\n10\n0\n20\n{W}\n30\n0\n11\n0\n21\n0\n31\n0\n")
        # Tiles
        for t in tiles:
            layer = "TILE_FRAC" if t.is_fractional else "TILE"
            f.write(f"0\nLINE\n8\n{layer}\n10\n{t.x0}\n20\n{t.y0}\n30\n{t.z1}\n11\n{t.x1}\n21\n{t.y0}\n31\n{t.z1}\n")
            f.write(f"0\nLINE\n8\n{layer}\n10\n{t.x1}\n20\n{t.y0}\n30\n{t.z1}\n11\n{t.x1}\n21\n{t.y1}\n31\n{t.z1}\n")
            f.write(f"0\nLINE\n8\n{layer}\n10\n{t.x1}\n20\n{t.y1}\n30\n{t.z1}\n11\n{t.x0}\n21\n{t.y1}\n31\n{t.z1}\n")
            f.write(f"0\nLINE\n8\n{layer}\n10\n{t.x0}\n20\n{t.y1}\n30\n{t.z1}\n11\n{t.x0}\n21\n{t.y0}\n31\n{t.z1}\n")
        f.write("0\nENDSEC\n0\nEOF\n")

class UnitSpin:
    UNIT_FACTORS = {"m": 1.0, "cm": 0.01, "mm": 0.001, "in": 0.0254}
    def __init__(self, mn_m, mx_m, val_m, step_m, default_unit="m"):
        self.widget = QtWidgets.QWidget()
        h = QHBoxLayout(self.widget)
        h.setContentsMargins(0, 0, 0, 0)
        self.spin = QDoubleSpinBox()
        self.spin.setDecimals(3)
        self.spin.setKeyboardTracking(False)
        self.spin.setFixedWidth(115)
        self.unit = QComboBox()
        self.unit.addItems(["m", "cm", "mm"])
        self.unit.setFixedWidth(55)
        self.unit.setCurrentText(default_unit)
        h.addWidget(self.spin)
        h.addWidget(self.unit)
        self.mn_m, self.mx_m, self.step_m = mn_m, mx_m, step_m
        self._apply_ranges(default_unit)
        self.set_value_m(val_m)
        self.unit.currentTextChanged.connect(self._on_unit_changed)

    def value_m(self):
        return self.spin.value() * self.UNIT_FACTORS[self.unit.currentText()]

    def set_value_m(self, m):
        self.spin.setValue(m / self.UNIT_FACTORS[self.unit.currentText()])

    def _apply_ranges(self, u):
        f = self.UNIT_FACTORS[u]
        self.spin.setRange(self.mn_m / f, self.mx_m / f)
        self.spin.setSingleStep(max(self.step_m / f, 0.001))

    def _on_unit_changed(self, u):
        cur = self.value_m()
        self._apply_ranges(u)
        self.set_value_m(cur)

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Room Tiles + Heating Pipes")
        self.resize(1400, 820)

        self.room = RoomSpec()
        self.tile = TileSpec()
        self.support = SupportSpec()
        self.heating = HeatingSpec()

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        
        splitter = QSplitter(QtCore.Qt.Horizontal)
        
        # LEFT: View
        self.view = GLRoomView()
        self.view.tilePicked.connect(self.on_tile_picked)
        splitter.addWidget(self.view)

        # RIGHT: Panel
        right_panel = QtWidgets.QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0,0,0,0)
        
        right_split = QSplitter(QtCore.Qt.Vertical)
        
        # Parameters Group
        params_box = QGroupBox("Parameters")
        form = QFormLayout(params_box)
        
        self.roomL = UnitSpin(0.1, 100.0, 5.0, 0.1, "m")
        self.roomW = UnitSpin(0.1, 100.0, 4.0, 0.1, "m")
        self.tileL = UnitSpin(0.05, 5.0, 0.6, 0.05, "m")
        self.tileW = UnitSpin(0.05, 5.0, 0.6, 0.05, "m")
        self.tileT = UnitSpin(0.001, 0.50, 0.04, 0.001, "m")
        self.plateR = UnitSpin(0.001, 1.0, 0.05, 0.001, "cm")
        self.plateH = UnitSpin(0.0001, 0.10, 0.002, 0.0001, "cm")
        
        btn_update = QPushButton("GENERATE / UPDATE")
        btn_update.clicked.connect(self.apply_and_regenerate)
        
        form.addRow("Room length (X):", self.roomL.widget)
        form.addRow("Room width (Y):", self.roomW.widget)
        form.addRow("Tile length (X):", self.tileL.widget)
        form.addRow("Tile width (Y):", self.tileW.widget)
        form.addRow("Tile thickness (Z):", self.tileT.widget)
        form.addRow("Plate radius:", self.plateR.widget)
        form.addRow("Plate height:", self.plateH.widget)
        form.addRow(btn_update)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(params_box)
        right_split.addWidget(scroll)

        # QR Group
        qr_box = QGroupBox("QR / Export")
        qr_layout = QVBoxLayout(qr_box)
        
        self.qr_label = QLabel("Right-click a tile\nto show its QR")
        self.qr_label.setFixedSize(250, 250)
        self.qr_label.setAlignment(QtCore.Qt.AlignCenter)
        self.qr_label.setStyleSheet("background:white;border:1px solid black;")
        
        self.btn_save_qr = QPushButton("Save shown QR...")
        self.btn_export_dxf = QPushButton("Export full layout to CAD (DXF)...")
        self.btn_export_dxf.clicked.connect(self.export_dxf)
        
        self.info_text = QPlainTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setPlaceholderText("Tile heating details appear here...")
        
        qr_layout.addWidget(self.qr_label)
        qr_layout.addWidget(self.btn_save_qr)
        qr_layout.addWidget(self.btn_export_dxf)
        qr_layout.addWidget(self.info_text)
        
        right_split.addWidget(qr_box)
        right_layout.addWidget(right_split)
        
        splitter.addWidget(right_panel)
        splitter.setSizes([900, 500])
        outer.addWidget(splitter)
        
        self._current_qr_pixmap = None
        self.apply_and_regenerate()

    def apply_and_regenerate(self):
        self.room.length_m = self.roomL.value_m()
        self.room.width_m = self.roomW.value_m()
        self.tile.length_m = self.tileL.value_m()
        self.tile.width_m = self.tileW.value_m()
        self.tile.thickness_m = self.tileT.value_m()
        self.support.plate_radius_m = self.plateR.value_m()
        self.support.plate_height_m = self.plateH.value_m()
        
        tiles, supports, z0, z1, circuit = compute_layout(self.room, self.tile, self.support, self.heating)
        
        self.tiles = tiles
        self.supports = supports
        self.circuit = circuit
        
        self.view.set_data(self.room, tiles, supports, circuit.pipe_parts, self.heating)

    def on_tile_picked(self, tile):
        if not tile: return
        payload = getattr(tile, "qr_payload", "")
        if payload:
            img = make_qr(payload).resize((250, 250))
            qimg = ImageQt(img)
            self._current_qr_pixmap = QtGui.QPixmap.fromImage(qimg)
            self.qr_label.setPixmap(self._current_qr_pixmap)
        
        self.info_text.setPlainText(
            f"Tile: {tile.tile_id}\n"
            f"Size: {tile.x1-tile.x0:.3f} x {tile.y1-tile.y0:.3f}\n"
            f"Pipe length: {tile.pipe_length_m:.3f} m\n"
            f"Temp In: {tile.pipe_inlet_temp_c:.1f} C\n"
            f"Temp Out: {tile.pipe_outlet_temp_c:.1f} C"
        )

    def export_dxf(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export DXF", "layout.dxf", "DXF (*.dxf)")
        if path:
            export_dxf(self.room, self.tiles, self.supports, self.circuit, path)