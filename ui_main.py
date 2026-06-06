# ui_main.py
import sys, os, json, math
from collections import Counter
from PyQt5 import QtCore, QtWidgets, QtGui
from PyQt5.QtWidgets import QDoubleSpinBox, QComboBox, QHBoxLayout, QVBoxLayout, QFormLayout, QGroupBox, QPushButton, QLabel, QSplitter, QScrollArea, QPlainTextEdit

# Imports
from models import RoomSpec, TileSpec, SupportSpec, HeatingSpec
from view_gl import GLRoomView, GLTileDetailView
from qr_engine import make_qr
from layout_engine import compute_layout
from en1264_engine import (
    BUILDING_LEVELS,
    FLOOR_COVERINGS,
    INSULATION_LEVELS,
    PIPE_TYPES,
    SCREED_TYPES,
    option_by_key,
    options_for_combo,
)

ROOM_PIPE_LAYOUT_NAME = "one_pipe_per_tile_snake"
X_PARTIAL_PLACEMENTS = (
    ("Right side", "right"),
    ("Left side", "left"),
    ("Split both sides", "center"),
    ("Custom offset", "custom"),
    ("Manual drag", "manual"),
)
Y_PARTIAL_PLACEMENTS = (
    ("Top side", "top"),
    ("Bottom side", "bottom"),
    ("Split both sides", "center"),
    ("Custom offset", "custom"),
    ("Manual drag", "manual"),
)
CONNECTION_DIRECTIONS = (
    ("Left", "left"),
    ("Right", "right"),
    ("Up", "up"),
    ("Down", "down"),
)

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
        self.spin.setDecimals(2)
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


class TemperatureSpin:
    def __init__(self, mn_c, mx_c, val_c, step_c=0.5, default_unit="°C"):
        self.widget = QtWidgets.QWidget()
        h = QHBoxLayout(self.widget)
        h.setContentsMargins(0, 0, 0, 0)
        self.spin = QDoubleSpinBox()
        self.spin.setDecimals(2)
        self.spin.setKeyboardTracking(False)
        self.spin.setMinimumWidth(115)
        self.spin.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.unit = QComboBox()
        self.unit.addItems(["°C", "°F", "K"])
        self.unit.setFixedWidth(70)
        self.unit.setCurrentText(default_unit)
        self._unit = default_unit
        h.addWidget(self.spin, 1)
        h.addWidget(self.unit)
        self.mn_c, self.mx_c, self.step_c = mn_c, mx_c, step_c
        self._apply_ranges(default_unit)
        self.set_value_c(val_c)
        self.unit.currentTextChanged.connect(self._on_unit_changed)

    def value_c(self):
        value = self.spin.value()
        unit = self.unit.currentText()
        if unit == "°F":
            return (value - 32.0) * 5.0 / 9.0
        if unit == "K":
            return value - 273.15
        return value

    def set_value_c(self, c):
        unit = self.unit.currentText()
        if unit == "°F":
            self.spin.setValue(c * 9.0 / 5.0 + 32.0)
        elif unit == "K":
            self.spin.setValue(c + 273.15)
        else:
            self.spin.setValue(c)

    def _from_c(self, c, unit):
        if unit == "°F":
            return c * 9.0 / 5.0 + 32.0
        if unit == "K":
            return c + 273.15
        return c

    def _apply_ranges(self, unit):
        self.spin.setRange(self._from_c(self.mn_c, unit), self._from_c(self.mx_c, unit))
        step = self.step_c * 9.0 / 5.0 if unit == "°F" else self.step_c
        self.spin.setSingleStep(step)

    def _on_unit_changed(self, unit):
        cur_c = self.value_c_from_unit(self._unit)
        self._unit = unit
        self._apply_ranges(unit)
        self.set_value_c(cur_c)

    def value_c_from_unit(self, unit):
        value = self.spin.value()
        if unit == "°F":
            return (value - 32.0) * 5.0 / 9.0
        if unit == "K":
            return value - 273.15
        return value


def make_double_spin(mn, mx, value, step, decimals=2):
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


def make_option_combo(options, current_key):
    combo = QComboBox()
    for label, key in options_for_combo(options):
        combo.addItem(label, key)
    index = combo.findData(current_key)
    combo.setCurrentIndex(index if index >= 0 else 0)
    return combo


def make_key_combo(items, current_key):
    combo = QComboBox()
    for label, key in items:
        combo.addItem(label, key)
    index = combo.findData(current_key)
    combo.setCurrentIndex(index if index >= 0 else 0)
    return combo


def combo_key(combo):
    return combo.currentData() or ""


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
        self.view.tileInspectRequested.connect(self.show_tile_detail)
        self.view.fractionalLayoutDragged.connect(self.on_fractional_layout_dragged)
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
        self.tilePartialX = make_key_combo(X_PARTIAL_PLACEMENTS, self.tile.partial_x_side)
        self.tilePartialY = make_key_combo(Y_PARTIAL_PLACEMENTS, self.tile.partial_y_side)
        self.tileOffsetX = UnitSpin(0.0, 100.0, self.tile.full_tile_offset_x_m, 0.01, "cm")
        self.tileOffsetY = UnitSpin(0.0, 100.0, self.tile.full_tile_offset_y_m, 0.01, "cm")
        self.tileOffsetX.widget.setToolTip("Custom/manual mode: divides the leftover X fractional width. Dragging controls where the strip is inserted.")
        self.tileOffsetY.widget.setToolTip("Custom/manual mode: divides the leftover Y fractional width. Dragging controls where the strip is inserted.")
        self.plateR = UnitSpin(0.001, 1.0, self.support.plate_radius_m, 0.001, "cm")
        self.plateH = UnitSpin(0.0001, 0.10, self.support.plate_height_m, 0.0001, "cm")
        self.columnR = UnitSpin(0.0005, 0.50, self.support.column_radius_m, 0.0005, "cm")
        self.columnH = UnitSpin(0.001, 2.0, self.support.column_height_m, 0.001, "cm")

        self.pipeD = UnitSpin(0.001, 0.10, self.heating.pipe_outer_diameter_m, 0.001, "mm")
        self.pipeDentFactor = make_double_spin(1.00, 3.00, self.heating.pipe_dent_width_factor, 0.05, 2)
        self.pipeDentFactor.setToolTip("Visual groove/dent width as a multiplier of the pipe diameter. Does not change hydraulic calculations.")
        self.pipeConnectionExtension = UnitSpin(0.0, 2.0, self.heating.pipe_connection_extension_m, 0.01, "cm")
        self.pipeConnectionExtension.widget.setToolTip("Length of inlet and outlet pipe tails outside the selected boundary tile.")
        self.pipeSpacing = UnitSpin(0.01, 1.0, self.heating.pipe_spacing_m, 0.01, "cm")
        self.edgeCover = UnitSpin(0.0, 1.0, self.heating.edge_cover_m, 0.005, "cm")
        self.topCover = UnitSpin(0.0, 0.50, self.heating.top_cover_m, 0.001, "mm")
        self.connectionTileNo = make_int_spin(0, 0, self.heating.inlet_tile_index, 1)
        self.connectionTileNo.setToolTip("Boundary tiles only. Numeric part of the tile ID, for example 6 for T006_x0_y6.")
        self.connectionDirection = make_key_combo(CONNECTION_DIRECTIONS, self.heating.connection_direction)
        self.connectionDirection.setToolTip("Corner tiles only: sets the shared parallel exit side for the inlet and outlet.")
        self.connectionSpacing = UnitSpin(0.0, 2.0, self.heating.pipe_connection_spacing_m, 0.01, "cm")
        self.connectionSpacing.widget.setToolTip("Spacing between inlet and outlet. On corner tiles, one straight tail stays fixed and the other tail moves.")
        self.targetHeat = make_double_spin(1.0, 300.0, self.heating.target_heat_flux_w_m2, 1.0, 2)
        self.waterDeltaT = make_double_spin(0.5, 30.0, self.heating.water_delta_t_k, 0.5, 2)
        self.roomTemp = TemperatureSpin(-50.0, 80.0, self.heating.room_temp_c, 0.5, "°C")
        self.floorCovering = make_option_combo(FLOOR_COVERINGS, self.heating.floor_covering)
        self.screedType = make_option_combo(SCREED_TYPES, self.heating.screed_type)
        self.enPipeType = make_option_combo(PIPE_TYPES, self.heating.en1264_pipe_type)
        self.insulationLevel = make_option_combo(INSULATION_LEVELS, self.heating.insulation_level)
        self.buildingLevel = make_option_combo(BUILDING_LEVELS, self.heating.building_level)
        self.cylinderDetail = make_int_spin(8, 96, self.support.cylinder_detail, 1)
        self.showPipes = QtWidgets.QCheckBox("Show pipes")
        self.showPipes.setChecked(True)
        self.showPipes.setToolTip("When unchecked, pipe routes are shown as surface dents.")
        self.tempColors = QtWidgets.QCheckBox("Temperature colors")
        self.tempColors.setChecked(True)
        self.tilePartialX.currentIndexChanged.connect(self._refresh_tile_offset_controls)
        self.tilePartialY.currentIndexChanged.connect(self._refresh_tile_offset_controls)
        self.enPipeType.currentIndexChanged.connect(self._sync_pipe_diameter_from_type)
        self.showPipes.stateChanged.connect(self.refresh_view_options)
        self.tempColors.stateChanged.connect(self.refresh_view_options)
        self._refresh_tile_offset_controls()

        btn_update = QPushButton("GENERATE / UPDATE")
        btn_update.clicked.connect(lambda: self.apply_and_regenerate())

        form.addRow("Room length (X):", self.roomL.widget)
        form.addRow("Room width (Y):", self.roomW.widget)
        add_section("Tiles")
        form.addRow("Tile length (X):", self.tileL.widget)
        form.addRow("Tile width (Y):", self.tileW.widget)
        form.addRow("Tile thickness (Z):", self.tileT.widget)
        form.addRow("X partial strip:", self.tilePartialX)
        form.addRow("Y partial strip:", self.tilePartialY)
        form.addRow("X full-tile offset:", self.tileOffsetX.widget)
        form.addRow("Y full-tile offset:", self.tileOffsetY.widget)
        add_section("Supports")
        form.addRow("Plate radius:", self.plateR.widget)
        form.addRow("Plate height:", self.plateH.widget)
        form.addRow("Column radius:", self.columnR.widget)
        form.addRow("Column height:", self.columnH.widget)
        add_section("Heating")
        form.addRow("Pipe outer diameter:", self.pipeD.widget)
        form.addRow("Dent width factor:", self.pipeDentFactor)
        form.addRow("Inlet/outlet extension:", self.pipeConnectionExtension.widget)
        form.addRow("Pipe spacing:", self.pipeSpacing.widget)
        form.addRow("Edge cover:", self.edgeCover.widget)
        form.addRow("Top cover:", self.topCover.widget)
        form.addRow("Inlet/Outlet tile number:", self.connectionTileNo)
        form.addRow("Inlet/Outlet direction:", self.connectionDirection)
        form.addRow("Inlet/Outlet spacing:", self.connectionSpacing.widget)
        add_section("EN 1264 Design")
        form.addRow("Floor covering:", self.floorCovering)
        form.addRow("Screed type:", self.screedType)
        form.addRow("Pipe type:", self.enPipeType)
        form.addRow("Insulation below:", self.insulationLevel)
        form.addRow("Building level:", self.buildingLevel)
        form.addRow("Target output (W/m²):", self.targetHeat)
        form.addRow("Water ΔT (K):", self.waterDeltaT)
        form.addRow("Room temp:", self.roomTemp.widget)
        form.addRow("Cylinder detail:", self.cylinderDetail)
        form.addRow(self.showPipes)
        form.addRow(self.tempColors)
        form.addRow(btn_update)

        add_section("Results")
        self.results_tiles = QLabel()
        self.results_pipe_types = QLabel()
        self.results_pipe = QLabel()
        self.results_supports = QLabel()
        for label in (self.results_tiles, self.results_pipe_types, self.results_pipe, self.results_supports):
            label.setWordWrap(True)
            label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        form.addRow("Tiles (by size):", self.results_tiles)
        form.addRow("Pipes (by type):", self.results_pipe_types)
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
        self._tile_detail_window = None
        self.apply_and_regenerate()

    def _sync_pipe_diameter_from_type(self):
        pipe = option_by_key(PIPE_TYPES, combo_key(self.enPipeType))
        self.pipeD.set_value_m(pipe.value)

    def _refresh_tile_offset_controls(self):
        self.tileOffsetX.widget.setEnabled(combo_key(self.tilePartialX) in ("custom", "manual"))
        self.tileOffsetY.widget.setEnabled(combo_key(self.tilePartialY) in ("custom", "manual"))

    def _set_combo_key(self, combo, key):
        index = combo.findData(key)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _axis_partial_count(self, axis):
        if axis == "x":
            total = self.roomL.value_m()
            size = self.tileL.value_m()
            placement = combo_key(self.tilePartialX)
            offset = self.tileOffsetX.value_m()
        else:
            total = self.roomW.value_m()
            size = self.tileW.value_m()
            placement = combo_key(self.tilePartialY)
            offset = self.tileOffsetY.value_m()

        size = max(float(size), 1e-9)
        full_count = int(math.floor((float(total) + 1e-9) / size))
        leftover = max(float(total) - full_count * size, 0.0)
        if leftover <= 1e-6:
            return 0, full_count, placement
        if placement in ("center", "split"):
            return 2, full_count, placement
        if placement in ("custom", "manual"):
            first = max(0.0, min(float(offset), leftover))
            count = int(first > 1e-6) + int(leftover - first > 1e-6)
            return max(1, count), full_count, placement
        return 1, full_count, placement

    def _default_partial_positions(self, axis, count, full_count, placement):
        if count <= 0:
            return []
        if placement in ("start", "left", "bottom"):
            positions = [0]
        elif placement in ("center", "split"):
            positions = [0, full_count]
        else:
            positions = [full_count]
        while len(positions) < count:
            positions.append(full_count)
        return positions[:count]

    def _move_manual_partial_strip(self, axis, fraction_index, insert_index):
        count, full_count, placement = self._axis_partial_count(axis)
        if count <= 0 or fraction_index is None or insert_index is None:
            return False

        attr = "partial_x_positions" if axis == "x" else "partial_y_positions"
        combo = self.tilePartialX if axis == "x" else self.tilePartialY
        positions = list(getattr(self.tile, attr, []))
        if placement != "manual" or len(positions) < count:
            positions = self._default_partial_positions(axis, count, full_count, placement)
        positions = [max(0, min(full_count, int(round(p)))) for p in positions[:count]]
        while len(positions) < count:
            positions.append(full_count)

        order = sorted(range(len(positions)), key=lambda i: (positions[i], i))
        target = order[min(max(int(fraction_index), 0), len(order) - 1)]
        positions[target] = max(0, min(full_count, int(round(insert_index))))

        setattr(self.tile, attr, positions)
        self._set_combo_key(combo, "manual")
        return True

    def on_fractional_layout_dragged(self, payload):
        changed = False
        if self._move_manual_partial_strip("x", payload.get("x_fraction_index"), payload.get("x_insert_index")):
            changed = True
        if self._move_manual_partial_strip("y", payload.get("y_fraction_index"), payload.get("y_insert_index")):
            changed = True
        if changed:
            self._refresh_tile_offset_controls()
            self.apply_and_regenerate(show_errors=bool(payload.get("final")))

    def apply_and_regenerate(self, show_errors=True):
        self.room.length_m = self.roomL.value_m()
        self.room.width_m = self.roomW.value_m()
        self.tile.length_m = self.tileL.value_m()
        self.tile.width_m = self.tileW.value_m()
        self.tile.thickness_m = self.tileT.value_m()
        self.tile.partial_x_side = combo_key(self.tilePartialX)
        self.tile.partial_y_side = combo_key(self.tilePartialY)
        self.tile.full_tile_offset_x_m = self.tileOffsetX.value_m()
        self.tile.full_tile_offset_y_m = self.tileOffsetY.value_m()
        if self.tile.partial_x_side != "manual":
            self.tile.partial_x_positions = []
        if self.tile.partial_y_side != "manual":
            self.tile.partial_y_positions = []
        self.support.plate_radius_m = self.plateR.value_m()
        self.support.plate_height_m = self.plateH.value_m()
        self.support.column_radius_m = self.columnR.value_m()
        self.support.column_height_m = self.columnH.value_m()
        self.support.cylinder_detail = self.cylinderDetail.value()
        self.heating.pipe_outer_diameter_m = self.pipeD.value_m()
        self.heating.pipe_dent_width_factor = self.pipeDentFactor.value()
        self.heating.pipe_connection_extension_m = self.pipeConnectionExtension.value_m()
        self.heating.pipe_spacing_m = self.pipeSpacing.value_m()
        self.heating.edge_cover_m = self.edgeCover.value_m()
        self.heating.top_cover_m = self.topCover.value_m()
        self.heating.inlet_tile_index = self.connectionTileNo.value()
        self.heating.outlet_tile_index = self.heating.inlet_tile_index
        self.heating.connection_direction = combo_key(self.connectionDirection)
        self.heating.pipe_connection_spacing_m = self.connectionSpacing.value_m()
        self.heating.target_heat_flux_w_m2 = self.targetHeat.value()
        self.heating.water_delta_t_k = self.waterDeltaT.value()
        self.heating.floor_covering = combo_key(self.floorCovering)
        self.heating.screed_type = combo_key(self.screedType)
        self.heating.en1264_pipe_type = combo_key(self.enPipeType)
        self.heating.insulation_level = combo_key(self.insulationLevel)
        self.heating.building_level = combo_key(self.buildingLevel)
        self.heating.room_temp_c = self.roomTemp.value_c()
        
        try:
            tiles, supports, z0, z1, circuit = compute_layout(self.room, self.tile, self.support, self.heating)
        except ValueError as exc:
            if show_errors:
                QtWidgets.QMessageBox.warning(self, "Invalid layout", str(exc))
            return
        
        self.tiles = tiles
        self.supports = supports
        self.circuit = circuit
        self._sync_connection_tile_controls()
        
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

    def _sync_connection_tile_controls(self):
        if not getattr(self, "tiles", None):
            return
        max_index = max(0, len(self.tiles) - 1)
        self.connectionTileNo.blockSignals(True)
        self.connectionTileNo.setRange(0, max_index)
        self.connectionTileNo.setValue(max(0, min(max_index, int(self.heating.inlet_tile_index))))
        self.connectionTileNo.blockSignals(False)

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
            self.results_pipe_types.setText("")
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

        straight_count = sum(1 for part in self.circuit.pipe_parts if part.kind == "straight")
        curved_count = sum(1 for part in self.circuit.pipe_parts if part.kind == "bend")
        self.results_pipe_types.setText(
            f"Straight: {straight_count}\n"
            f"Curved: {curved_count}\n"
            f"Total: {straight_count + curved_count}"
        )

        active_tiles = [t for t in self.tiles if t.pipe_length_m > 1e-9]
        avg_out = 0.0
        if active_tiles:
            avg_out = sum(t.pipe_outlet_temp_c for t in active_tiles) / len(active_tiles)

        self.results_pipe.setText(
            f"Layout: {ROOM_PIPE_LAYOUT_NAME}\n"
            f"Pipe orientation: {self.circuit.pipe_orientation or 'auto'}\n"
            f"Inlet/Outlet tile: {self.circuit.inlet_tile_id}\n"
            f"Inlet/Outlet direction: {self.connectionDirection.currentText()}\n"
            f"Inlet/Outlet spacing: {self.heating.pipe_connection_spacing_m * 100.0:.1f} cm\n"
            f"Return route: follows final bend direction\n"
            f"Tile strip X/Y: {self.tilePartialX.currentText()} / {self.tilePartialY.currentText()}\n"
            f"Total room pipe length: {self.circuit.total_length_m:.2f} m\n"
            f"Inlet/outlet extension: {self.heating.pipe_connection_extension_m * 100.0:.1f} cm\n"
            f"Dent/groove width: {self.heating.pipe_outer_diameter_m * self.heating.pipe_dent_width_factor * 1000.0:.1f} mm\n"
            f"EN 1264 target output: {self.heating.target_heat_flux_w_m2:.1f} W/m²\n"
            f"Design output: {self.heating.design_heat_flux_w_m2:.1f} W/m²\n"
            f"Water-side heat load: {self.heating.total_heat_load_w:.0f} W\n"
            f"EN log-mean water temp: {self.heating.mean_water_temp_c:.2f} °C\n"
            f"Supply temp: {self.circuit.inlet_temp_c:.2f} °C\n"
            f"Return temp: {self.circuit.outlet_temp_c:.2f} °C\n"
            f"Target water ΔT: {self.heating.water_delta_t_k:.2f} K\n"
            f"Calculated water ΔT: {self.heating.calculated_water_delta_t_k:.2f} K\n"
            f"Floor surface temp: {self.heating.floor_surface_temp_c:.2f} °C\n"
            f"Mass flow: {self.heating.mass_flow_kg_h:.1f} kg/h\n"
            f"Water density: {self.heating.water_density_kg_m3:.1f} kg/m³\n"
            f"Volume flow: {self.heating.volume_flow_l_min:.3f} L/min\n"
            f"EN K_H: {self.heating.equivalent_heat_transmission_w_m2_k:.3f} W/m²K\n"
            f"Log mean Δθ_H: {self.heating.log_mean_delta_theta_k:.3f} K\n"
            f"Characteristic exponent n: {self.heating.characteristic_exponent:.2f}\n"
            f"Pipe temperature profile k: {self.heating.temperature_decay_factor:.4f}\n"
            f"EN 1264 status: {self.heating.en1264_status or 'OK'}\n"
            f"Tiles covered: {len(active_tiles)} / {len(self.tiles)}\n"
            f"Average active-tile outlet temp: {avg_out:.1f} °C"
        )
        self.results_supports.setText(str(len(self.supports)))

    def on_tile_picked(self, tile):
        if not tile: return
        payload = getattr(tile, "qr_payload", "")
        if payload:
            try:
                img = make_qr(payload).resize((300, 300)).convert("RGBA")
                qimg = QtGui.QImage(
                    img.tobytes("raw", "RGBA"),
                    img.width,
                    img.height,
                    QtGui.QImage.Format_RGBA8888
                ).copy()
                self._current_qr_pixmap = QtGui.QPixmap.fromImage(qimg)
                self.qr_label.setPixmap(self._current_qr_pixmap)
            except Exception as exc:
                self._current_qr_pixmap = None
                self.qr_label.setText("QR could not be created")
                self.info_text.setPlainText(f"Tile: {tile.tile_id}\nQR error: {exc}")
                return

        straight_count = sum(1 for p in tile.pipe_parts if p.kind == "straight")
        curved_count = sum(1 for p in tile.pipe_parts if p.kind == "bend")
        
        self.info_text.setPlainText(
            f"Tile: {tile.tile_id}\n"
            f"Size: {tile.x1-tile.x0:.3f} m × {tile.y1-tile.y0:.3f} m\n"
            f"Pipe route: {ROOM_PIPE_LAYOUT_NAME}\n"
            f"Straight pipe sections: {straight_count}\n"
            f"Curved pipe sections: {curved_count}\n"
            f"Pipe length: {tile.pipe_length_m:.3f} m\n"
            f"Pipe entry distance: {getattr(tile, 'pipe_entry_distance_m', 0.0):.3f} m\n"
            f"Pipe exit distance: {getattr(tile, 'pipe_exit_distance_m', 0.0):.3f} m\n"
            f"Tile entry: {tile.pipe_inlet_temp_c:.2f} °C\n"
            f"Tile exit: {tile.pipe_outlet_temp_c:.2f} °C\n"
            f"Tile ΔT: {tile.pipe_inlet_temp_c - tile.pipe_outlet_temp_c:.2f} K\n"
            f"Supply temp: {self.circuit.inlet_temp_c:.2f} °C\n"
            f"Return temp: {self.circuit.outlet_temp_c:.2f} °C\n"
            f"Calculated water ΔT: {self.heating.calculated_water_delta_t_k:.2f} K\n"
            f"Volume flow: {self.heating.volume_flow_l_min:.3f} L/min\n"
            f"EN log-mean water temp: {self.heating.mean_water_temp_c:.2f} °C\n"
            f"Floor surface temp: {self.heating.floor_surface_temp_c:.2f} °C"
        )

    def show_tile_detail(self, tile):
        if not tile:
            return
        if self._tile_detail_window is not None:
            self._tile_detail_window.close()

        dialog = QtWidgets.QDialog(self)
        dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        dialog.setWindowTitle(f"Tile detail - {tile.tile_id}")
        dialog.resize(900, 680)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(8, 8, 8, 8)

        controls = QtWidgets.QWidget(dialog)
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        show_pipe = QtWidgets.QCheckBox("Show pipe", controls)
        show_pipe.setChecked(True)
        controls_layout.addWidget(show_pipe)
        controls_layout.addStretch(1)
        layout.addWidget(controls)

        detail_view = GLTileDetailView(tile, tile.pipe_parts, self.heating, dialog)
        show_pipe.toggled.connect(detail_view.set_show_pipe)
        layout.addWidget(detail_view)
        self._tile_detail_window = dialog

        def forget_window(*_):
            if self._tile_detail_window is dialog:
                self._tile_detail_window = None

        dialog.destroyed.connect(forget_window)
        dialog.show()

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
