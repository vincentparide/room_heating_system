# ui_main.py
import sys, os, json
from collections import Counter
from PyQt5 import QtCore, QtWidgets, QtGui
from PyQt5.QtWidgets import QDoubleSpinBox, QComboBox, QHBoxLayout, QVBoxLayout, QFormLayout, QGroupBox, QPushButton, QLabel, QSplitter, QScrollArea, QPlainTextEdit
from PIL.ImageQt import ImageQt

# Imports
from models import RoomSpec, TileSpec, SupportSpec, HeatingSpec
from view_gl import GLRoomView
from qr_engine import make_qr
from layout_engine import compute_layout

ROOM_PIPE_LAYOUT_NAME = "one_pipe_per_tile_snake"

# DXF Export Function (Inline for simplicity)
def export_dxf(room, tiles, supports, circuit, filepath, support_spec=None):
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
        # Support plate positions
        support_radius = support_spec.plate_radius_m if support_spec else 0.05
        for s in supports:
            f.write(f"0\nCIRCLE\n8\nSUPPORT_PLATE\n10\n{s.cx}\n20\n{s.cy}\n30\n{s.z0}\n40\n{support_radius}\n")
        # Heating pipe center lines
        for part in getattr(circuit, "pipe_parts", []):
            layer = "PIPE_BEND" if part.kind == "bend" else "PIPE_STRAIGHT"
            for p0, p1 in zip(part.points[:-1], part.points[1:]):
                f.write(f"0\nLINE\n8\n{layer}\n10\n{p0.x}\n20\n{p0.y}\n30\n{p0.z}\n11\n{p1.x}\n21\n{p1.y}\n31\n{p1.z}\n")
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
        self.spin.setMinimumWidth(115)
        self.spin.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.unit = QComboBox()
        self.unit.addItems(["m", "cm", "mm"])
        self.unit.setFixedWidth(70)
        self.unit.setCurrentText(default_unit)
        self._unit = default_unit
        h.addWidget(self.spin, 1)
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
        cur = self.spin.value() * self.UNIT_FACTORS[self._unit]
        self._unit = u
        self._apply_ranges(u)
        self.set_value_m(cur)

def make_double_spin(mn, mx, value, step, decimals=3):
    spin = QDoubleSpinBox()
    spin.setDecimals(decimals)
    spin.setRange(mn, mx)
    spin.setSingleStep(step)
    spin.setKeyboardTracking(False)
    spin.setValue(value)
    return spin

def make_int_spin(mn, mx, value, step=1):
    spin = QtWidgets.QSpinBox()
    spin.setRange(mn, mx)
    spin.setSingleStep(step)
    spin.setKeyboardTracking(False)
    spin.setValue(value)
    return spin

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
        params_layout = QVBoxLayout(params_box)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        params_layout.addLayout(form)

        def add_section(title):
            label = QLabel(f"-- {title} --")
            label.setStyleSheet("margin-top: 8px;")
            form.addRow(label)

        self.roomL = UnitSpin(0.1, 100.0, self.room.length_m, 0.1, "m")
        self.roomW = UnitSpin(0.1, 100.0, self.room.width_m, 0.1, "m")
        self.tileL = UnitSpin(0.05, 5.0, self.tile.length_m, 0.05, "m")
        self.tileW = UnitSpin(0.05, 5.0, self.tile.width_m, 0.05, "m")
        self.tileT = UnitSpin(0.001, 0.50, self.tile.thickness_m, 0.001, "m")
        self.plateR = UnitSpin(0.001, 1.0, self.support.plate_radius_m, 0.001, "cm")
        self.plateH = UnitSpin(0.0001, 0.10, self.support.plate_height_m, 0.0001, "cm")
        self.columnR = UnitSpin(0.0005, 0.50, self.support.column_radius_m, 0.0005, "cm")
        self.columnH = UnitSpin(0.001, 2.0, self.support.column_height_m, 0.001, "cm")

        self.pipeLayout = QComboBox()
        self.pipeLayout.addItems(["meander", ROOM_PIPE_LAYOUT_NAME])
        self.pipeLayout.setCurrentText(self.heating.pipe_layout)
        self.pipeLayout.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.pipeD = UnitSpin(0.001, 0.10, self.heating.pipe_outer_diameter_m, 0.001, "mm")
        self.pipeSpacing = UnitSpin(0.01, 1.0, self.heating.pipe_spacing_m, 0.01, "cm")
        self.edgeCover = UnitSpin(0.0, 1.0, self.heating.edge_cover_m, 0.005, "cm")
        self.topCover = UnitSpin(0.0, 0.50, self.heating.top_cover_m, 0.001, "mm")
        self.supplyTemp = make_double_spin(-50.0, 150.0, self.heating.inlet_temp_c, 0.5, 1)
        self.roomTemp = make_double_spin(-50.0, 80.0, self.heating.room_temp_c, 0.5, 1)
        self.lossCoeff = make_double_spin(0.0, 10.0, self.heating.heat_loss_per_m_k, 0.01, 3)
        self.cylinderDetail = make_int_spin(8, 96, self.support.cylinder_detail, 1)
        self.showPipes = QtWidgets.QCheckBox("Show pipes")
        self.showPipes.setChecked(True)
        self.tempColors = QtWidgets.QCheckBox("Temperature colors")
        self.tempColors.setChecked(True)
        self.showPipes.stateChanged.connect(self.refresh_view_options)
        self.tempColors.stateChanged.connect(self.refresh_view_options)

        btn_update = QPushButton("GENERATE / UPDATE")
        btn_update.clicked.connect(self.apply_and_regenerate)

        form.addRow("Room length (X):", self.roomL.widget)
        form.addRow("Room width (Y):", self.roomW.widget)
        add_section("Tiles")
        form.addRow("Tile length (X):", self.tileL.widget)
        form.addRow("Tile width (Y):", self.tileW.widget)
        form.addRow("Tile thickness (Z):", self.tileT.widget)
        add_section("Supports")
        form.addRow("Plate radius:", self.plateR.widget)
        form.addRow("Plate height:", self.plateH.widget)
        form.addRow("Column radius:", self.columnR.widget)
        form.addRow("Column height:", self.columnH.widget)
        add_section("Heating")
        form.addRow("Pipe layout:", self.pipeLayout)
        form.addRow("Pipe outer diameter:", self.pipeD.widget)
        form.addRow("Pipe spacing:", self.pipeSpacing.widget)
        form.addRow("Edge cover:", self.edgeCover.widget)
        form.addRow("Top cover:", self.topCover.widget)
        form.addRow("Supply temp (°C):", self.supplyTemp)
        form.addRow("Room temp (°C):", self.roomTemp)
        form.addRow("Loss coeff (/m):", self.lossCoeff)
        form.addRow("Cylinder detail:", self.cylinderDetail)
        form.addRow(self.showPipes)
        form.addRow(self.tempColors)
        form.addRow(btn_update)

        add_section("Results")
        self.results_tiles = QLabel()
        self.results_pipe = QLabel()
        self.results_supports = QLabel()
        for label in (self.results_tiles, self.results_pipe, self.results_supports):
            label.setWordWrap(True)
            label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        form.addRow("Tiles (by size):", self.results_tiles)
        form.addRow("Pipe summary:", self.results_pipe)
        form.addRow("Total supports:", self.results_supports)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(params_box)
        right_split.addWidget(scroll)

        # QR Group
        qr_box = QGroupBox("QR / Export")
        qr_layout = QVBoxLayout(qr_box)
        
        self.qr_label = QLabel("Right-click a tile\nto show its QR")
        self.qr_label.setMinimumHeight(300)
        self.qr_label.setMaximumHeight(320)
        self.qr_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.qr_label.setAlignment(QtCore.Qt.AlignCenter)
        self.qr_label.setStyleSheet("background:white;border:1px solid black;")
        
        self.btn_save_qr = QPushButton("Save shown QR...")
        self.btn_export_dxf = QPushButton("Export full layout to CAD (DXF)...")
        self.btn_save_qr.clicked.connect(self.save_current_qr)
        self.btn_export_dxf.clicked.connect(self.export_dxf)
        
        self.info_text = QPlainTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setPlaceholderText("Tile heating details appear here...")
        self.info_text.setMinimumHeight(110)
        
        qr_layout.addWidget(self.qr_label)
        qr_layout.addWidget(self.btn_save_qr)
        qr_layout.addWidget(self.btn_export_dxf)
        qr_layout.addWidget(self.info_text)
        
        right_split.addWidget(qr_box)
        right_split.setSizes([500, 380])
        right_split.setStretchFactor(0, 1)
        right_split.setStretchFactor(1, 0)
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
        self.support.column_radius_m = self.columnR.value_m()
        self.support.column_height_m = self.columnH.value_m()
        self.support.cylinder_detail = self.cylinderDetail.value()
        self.heating.pipe_layout = self.pipeLayout.currentText()
        self.heating.pipe_outer_diameter_m = self.pipeD.value_m()
        self.heating.pipe_spacing_m = self.pipeSpacing.value_m()
        self.heating.edge_cover_m = self.edgeCover.value_m()
        self.heating.top_cover_m = self.topCover.value_m()
        self.heating.inlet_temp_c = self.supplyTemp.value()
        self.heating.room_temp_c = self.roomTemp.value()
        self.heating.heat_loss_per_m_k = self.lossCoeff.value()
        
        tiles, supports, z0, z1, circuit = compute_layout(self.room, self.tile, self.support, self.heating)
        
        self.tiles = tiles
        self.supports = supports
        self.circuit = circuit
        
        self.view.set_data(
            self.room,
            tiles,
            supports,
            circuit.pipe_parts,
            self.heating,
            self.support,
            self.showPipes.isChecked(),
            self.tempColors.isChecked()
        )
        self.update_results()

    def refresh_view_options(self):
        if not hasattr(self, "tiles"):
            return
        self.view.set_data(
            self.room,
            self.tiles,
            self.supports,
            self.circuit.pipe_parts,
            self.heating,
            self.support,
            self.showPipes.isChecked(),
            self.tempColors.isChecked()
        )

    def update_results(self):
        if not getattr(self, "tiles", None):
            self.results_tiles.setText("")
            self.results_pipe.setText("")
            self.results_supports.setText("0")
            return

        counts = Counter()
        for tile in self.tiles:
            dx = round(tile.x1 - tile.x0, 3)
            dy = round(tile.y1 - tile.y0, 3)
            counts[(min(dx, dy), max(dx, dy))] += 1

        tile_lines = []
        for (a, b), count in sorted(counts.items(), key=lambda item: (-item[1], item[0][0], item[0][1])):
            tile_lines.append(f"{count} × {a:.3f} m × {b:.3f} m")
        self.results_tiles.setText("\n".join(tile_lines))

        active_tiles = [t for t in self.tiles if t.pipe_length_m > 1e-9]
        avg_out = 0.0
        if active_tiles:
            avg_out = sum(t.pipe_outlet_temp_c for t in active_tiles) / len(active_tiles)

        self.results_pipe.setText(
            f"Layout: {ROOM_PIPE_LAYOUT_NAME}\n"
            f"Return row: top tile row to outlet\n"
            f"Total room pipe length: {self.circuit.total_length_m:.2f} m\n"
            f"Room outlet temp: {self.circuit.outlet_temp_c:.1f} °C\n"
            f"Tiles crossed: {len(active_tiles)}\n"
            f"Average active-tile outlet temp: {avg_out:.1f} °C"
        )
        self.results_supports.setText(str(len(self.supports)))

    def on_tile_picked(self, tile):
        if not tile: return
        payload = getattr(tile, "qr_payload", "")
        if payload:
            img = make_qr(payload).resize((300, 300)).convert("RGBA")
            qimg = QtGui.QImage(
                img.tobytes("raw", "RGBA"),
                img.width,
                img.height,
                QtGui.QImage.Format_RGBA8888
            ).copy()
            self._current_qr_pixmap = QtGui.QPixmap.fromImage(qimg)
            self.qr_label.setPixmap(self._current_qr_pixmap)

        straight_count = sum(1 for p in tile.pipe_parts if p.kind == "straight")
        curved_count = sum(1 for p in tile.pipe_parts if p.kind == "bend")
        
        self.info_text.setPlainText(
            f"Tile: {tile.tile_id}\n"
            f"Size: {tile.x1-tile.x0:.3f} m × {tile.y1-tile.y0:.3f} m\n"
            f"Pipe layout: {ROOM_PIPE_LAYOUT_NAME}\n"
            f"Straight pipe sections: {straight_count}\n"
            f"Curved pipe sections: {curved_count}\n"
            f"Pipe length: {tile.pipe_length_m:.3f} m\n"
            f"Tile entry: {tile.pipe_inlet_temp_c:.2f} °C\n"
            f"Tile exit: {tile.pipe_outlet_temp_c:.2f} °C\n"
            f"Room inlet: {self.circuit.inlet_temp_c:.2f} °C\n"
            f"Room outlet: {self.circuit.outlet_temp_c:.2f} °C"
        )

    def save_current_qr(self):
        if not self._current_qr_pixmap:
            QtWidgets.QMessageBox.information(self, "Save QR", "Right-click a tile first to show its QR code.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save QR", "tile_qr.png", "PNG (*.png)")
        if path:
            if not path.lower().endswith(".png"):
                path += ".png"
            self._current_qr_pixmap.save(path, "PNG")

    def export_dxf(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export DXF", "layout.dxf", "DXF (*.dxf)")
        if path:
            export_dxf(self.room, self.tiles, self.supports, self.circuit, path, self.support)
