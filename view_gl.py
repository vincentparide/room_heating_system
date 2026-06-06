# view_gl.py
import math
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtWidgets import QOpenGLWidget
from OpenGL.GL import *
from OpenGL.GLU import *

class GLRoomView(QOpenGLWidget):
    tilePicked = QtCore.pyqtSignal(object)
    tileInspectRequested = QtCore.pyqtSignal(object)
    fractionalLayoutDragged = QtCore.pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.room = None
        self.tiles = []
        self.supports = []
        self.pipes = []
        self.heating = None # Added to support temperature colors
        self.support_spec = None
        self.show_pipes = True
        self.temperature_colors = True
        self._pipe_display_list = None
        self._pipe_display_list_dirty = True
        self._dent_display_list = None
        self._dent_display_list_dirty = True

        self.azimuth = -90.0
        self.elevation = 88.0
        self.distance = 9.0
        self._user_moved_camera = False
        self._last_pos = None
        self._fractional_drag = None
        self._fractional_drag_candidate = None
        self._left_press_pos = None
        self._left_press_tile = None
        self._left_drag_started = False
        self.selected_tile = None

    def set_data(self, room, tiles, supports, pipes, heating=None,
                 support_spec=None, show_pipes=True, temperature_colors=True):
        self.room = room
        self.tiles = tiles
        self.supports = supports
        self.pipes = pipes or []
        self.heating = heating  # Save heating specs for temperature gradient
        self.support_spec = support_spec
        self.show_pipes = show_pipes
        self.temperature_colors = temperature_colors
        self._pipe_display_list_dirty = True
        self._dent_display_list_dirty = True
        if not self._user_moved_camera:
            self._fit_initial_camera()
        self.update()

    def _fit_initial_camera(self):
        if not self.room:
            return
        span = max(float(self.room.length_m), float(self.room.width_m), 1.0)
        self.azimuth = -90.0
        self.elevation = 88.0
        self.distance = max(4.0, min(80.0, 1.8 * span + 1.0))
        
    def initializeGL(self):
        glClearColor(0.07, 0.08, 0.10, 1.0)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glLightfv(GL_LIGHT0, GL_POSITION, (4.0, 6.0, 10.0, 1.0))
        glEnable(GL_COLOR_MATERIAL)
        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)

    def resizeGL(self, w, h):
        glViewport(0, 0, w, max(h, 1))
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(45.0, w / max(h, 1), 0.05, 200.0)
        glMatrixMode(GL_MODELVIEW)

    def _apply_camera(self):
        if not self.room:
            return

        eye, center, up = self._camera_vectors()
        gluLookAt(
            eye[0], eye[1], eye[2],
            center[0], center[1], center[2],
            up[0], up[1], up[2]
        )

    def _camera_vectors(self):
        cx = self.room.length_m * 0.5
        cy = self.room.width_m * 0.5
        center = (cx, cy, 0.0)
        az = math.radians(self.azimuth)
        el = math.radians(self.elevation)
        eye = (
            cx + self.distance * math.cos(el) * math.cos(az),
            cy + self.distance * math.cos(el) * math.sin(az),
            self.distance * math.sin(el)
        )
        up = (
            -math.sin(el) * math.cos(az),
            -math.sin(el) * math.sin(az),
            math.cos(el)
        )
        return eye, center, up

    def _screen_to_world_on_tile_plane(self, x, y):
        if not self.room or not self.tiles:
            return None

        def sub(a, b):
            return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

        def add(a, b):
            return (a[0] + b[0], a[1] + b[1], a[2] + b[2])

        def scale(v, s):
            return (v[0] * s, v[1] * s, v[2] * s)

        def cross(a, b):
            return (
                a[1] * b[2] - a[2] * b[1],
                a[2] * b[0] - a[0] * b[2],
                a[0] * b[1] - a[1] * b[0]
            )

        def normalize(v):
            length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
            if length < 1e-12:
                return (0.0, 0.0, 0.0)
            return (v[0] / length, v[1] / length, v[2] / length)

        eye, center, up_hint = self._camera_vectors()
        forward = normalize(sub(center, eye))
        right = normalize(cross(forward, up_hint))
        up = normalize(cross(right, forward))

        w = max(self.width(), 1)
        h = max(self.height(), 1)
        aspect = w / h
        tan_half_fov = math.tan(math.radians(45.0) * 0.5)
        ndc_x = (2.0 * x / w - 1.0) * aspect * tan_half_fov
        ndc_y = (1.0 - 2.0 * y / h) * tan_half_fov
        ray = normalize(add(add(forward, scale(right, ndc_x)), scale(up, ndc_y)))

        if abs(ray[2]) < 1e-12:
            return None
        z_plane = self.tiles[0].z1
        t = (z_plane - eye[2]) / ray[2]
        if t < 0.0:
            return None

        px = eye[0] + ray[0] * t
        py = eye[1] + ray[1] * t
        return px, py

    def _pick_tile_from_screen(self, x, y):
        pos = self._screen_to_world_on_tile_plane(x, y)
        if pos is None:
            return None
        px, py = pos
        for tile in self.tiles:
            if tile.x0 <= px <= tile.x1 and tile.y0 <= py <= tile.y1:
                return tile
        return None

    def _axis_fractional_info(self, axis):
        if not self.room or not self.tiles:
            return None
        if axis == "x":
            total = self.room.length_m
            intervals = sorted({(round(t.x0, 9), round(t.x1, 9)) for t in self.tiles})
        else:
            total = self.room.width_m
            intervals = sorted({(round(t.y0, 9), round(t.y1, 9)) for t in self.tiles})
        spans = [(a, b, b - a) for a, b in intervals if b - a > 1e-9]
        if not spans:
            return None
        full_span = max(span for _, _, span in spans)
        full = [(a, b, span) for a, b, span in spans if span >= full_span - 1e-6]
        fractional_spans = [(a, b, span) for a, b, span in spans if span < full_span - 1e-6]
        fractional = [(i, a, b, span) for i, (a, b, span) in enumerate(fractional_spans)]
        if not fractional:
            return None

        return {
            "total": total,
            "leftover": sum(span for _, _, _, span in fractional),
            "full": full,
            "fractional": fractional,
        }

    def _fractional_drag_at(self, x, y):
        pos = self._screen_to_world_on_tile_plane(x, y)
        if pos is None:
            return None
        px, py = pos
        x_info = self._axis_fractional_info("x")
        y_info = self._axis_fractional_info("y")

        def hit(info, value):
            if not info or info["leftover"] <= 1e-6:
                return None
            for fractional_index, a, b, _ in info["fractional"]:
                if a - 1e-6 <= value <= b + 1e-6:
                    return fractional_index
            return None

        x_index = hit(x_info, px)
        y_index = hit(y_info, py)
        if x_index is None and y_index is None:
            return None
        return {
            "start_x": px,
            "start_y": py,
            "x_info": x_info if x_index is not None else None,
            "y_info": y_info if y_index is not None else None,
            "x_index": x_index,
            "y_index": y_index,
        }

    def _emit_fractional_drag(self, x, y, final=False):
        if not self._fractional_drag:
            return
        pos = self._screen_to_world_on_tile_plane(x, y)
        if pos is None:
            return
        px, py = pos
        drag = self._fractional_drag
        payload = {
            "x_fraction_index": None,
            "x_insert_index": None,
            "y_fraction_index": None,
            "y_insert_index": None,
            "final": final,
        }

        def insertion_index(info, value):
            return sum(1 for a, b, _ in info["full"] if value > 0.5 * (a + b))

        if drag.get("x_info"):
            info = drag["x_info"]
            payload["x_fraction_index"] = drag.get("x_index")
            payload["x_insert_index"] = insertion_index(info, px)
        if drag.get("y_info"):
            info = drag["y_info"]
            payload["y_fraction_index"] = drag.get("y_index")
            payload["y_insert_index"] = insertion_index(info, py)

        self.fractionalLayoutDragged.emit(payload)

    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()

        if not self.room:
            return

        self._apply_camera()

        # --- DRAW ORDER FOR GLASS EFFECT ---
        
        # 1. Supports (Background/Underneath)
        self._draw_ground()
        self._draw_axes()
        for s in self.supports:
            self._draw_support(s)
            
        # 2. Tile Bodies (Opaque Bottoms & Sides) -> Hides pipes from below
        self._draw_tile_bodies()
        
        # 3. Pipes (Embedded inside)
        if self.show_pipes and self.pipes:
            self.draw_pipes()

        # 4. Tile Tops (Transparent Glass) -> Allows seeing pipes from above
        self._draw_tile_tops()

        # 4b. Pipe Dents (Surface grooves shown when pipes are hidden)
        if not self.show_pipes and self.pipes:
            self.draw_pipe_dents()
        
        # 5. Edges (Wireframe on top)
        self._draw_tile_edges()

    def _draw_ground(self):
        glDisable(GL_LIGHTING)
        glEnable(GL_BLEND)
        glDepthMask(GL_FALSE)
        glColor4f(0.18, 0.20, 0.24, 0.22)
        glBegin(GL_QUADS)
        pad = 1.0
        glVertex3f(-pad, -pad, 0.0)
        glVertex3f(self.room.length_m + pad, -pad, 0.0)
        glVertex3f(self.room.length_m + pad, self.room.width_m + pad, 0.0)
        glVertex3f(-pad, self.room.width_m + pad, 0.0)
        glEnd()
        glDepthMask(GL_TRUE)
        glEnable(GL_LIGHTING)
    def _draw_axes(self):
        glDisable(GL_LIGHTING)
        glLineWidth(3.0)
        origin = (0.0, 0.0, 0.5)
        L = 0.6
        glColor3f(1.0, 0.25, 0.25); glBegin(GL_LINES); glVertex3f(*origin); glVertex3f(origin[0] + L, origin[1], origin[2]); glEnd()
        glColor3f(0.25, 1.0, 0.25); glBegin(GL_LINES); glVertex3f(*origin); glVertex3f(origin[0], origin[1] + L, origin[2]); glEnd()
        glColor3f(0.35, 0.55, 1.0); glBegin(GL_LINES); glVertex3f(*origin); glVertex3f(origin[0], origin[1], origin[2] + L); glEnd()
        glEnable(GL_LIGHTING)

    def _draw_support(self, s):
        cx, cy = s.cx, s.cy
        ss = self.support_spec
        plate_r = ss.plate_radius_m if ss else 0.05
        plate_h = ss.plate_height_m if ss else 0.002
        col_r = ss.column_radius_m if ss else 0.002
        col_h = ss.column_height_m if ss else 0.15
        detail = max(8, int(ss.cylinder_detail if ss else 24))

        quad = gluNewQuadric()

        def draw_cylinder(z, radius, height, color):
            glColor3f(*color)
            glPushMatrix()
            glTranslatef(cx, cy, z)
            gluCylinder(quad, radius, radius, height, detail, 1)
            gluDisk(quad, 0.0, radius, detail, 1)
            glTranslatef(0.0, 0.0, height)
            gluDisk(quad, 0.0, radius, detail, 1)
            glPopMatrix()

        draw_cylinder(s.z0, plate_r, plate_h, (0.70, 0.70, 0.75))
        draw_cylinder(s.z0 + plate_h, col_r, col_h, (0.55, 0.55, 0.60))
        draw_cylinder(s.z0 + plate_h + col_h, plate_r, plate_h, (0.70, 0.70, 0.75))

        gluDeleteQuadric(quad)

    def _draw_tile_bodies(self):
        # Opaque Bottoms and Sides
        for t in self.tiles:
            if self.selected_tile is t:
                glColor3f(1.0, 0.85, 0.25) # Selected highlight
            elif t.is_fractional:
                glColor3f(0.45, 0.72, 1.00) # Fractional blue
            else:
                glColor3f(0.10, 0.35, 0.95) # Standard blue

            # Bottom Face
            glBegin(GL_QUADS)
            glNormal3f(0, 0, -1)
            glVertex3f(t.x0, t.y0, t.z0); glVertex3f(t.x1, t.y0, t.z0)
            glVertex3f(t.x1, t.y1, t.z0); glVertex3f(t.x0, t.y1, t.z0)
            glEnd()

            # Sides (Front, Back, Left, Right)
            glBegin(GL_QUADS)
            # Front
            glNormal3f(0, -1, 0)
            glVertex3f(t.x0, t.y0, t.z0); glVertex3f(t.x1, t.y0, t.z0)
            glVertex3f(t.x1, t.y0, t.z1); glVertex3f(t.x0, t.y0, t.z1)
            # Back
            glNormal3f(0, 1, 0)
            glVertex3f(t.x0, t.y1, t.z0); glVertex3f(t.x1, t.y1, t.z0)
            glVertex3f(t.x1, t.y1, t.z1); glVertex3f(t.x0, t.y1, t.z1)
            # Left
            glNormal3f(-1, 0, 0)
            glVertex3f(t.x0, t.y0, t.z0); glVertex3f(t.x0, t.y1, t.z0)
            glVertex3f(t.x0, t.y1, t.z1); glVertex3f(t.x0, t.y0, t.z1)
            # Right
            glNormal3f(1, 0, 0)
            glVertex3f(t.x1, t.y0, t.z0); glVertex3f(t.x1, t.y1, t.z0)
            glVertex3f(t.x1, t.y1, t.z1); glVertex3f(t.x1, t.y0, t.z1)
            glEnd()

    def _temp_to_rgb(self, temp_c):
        if not self.heating: return (0.8, 0.4, 0.1)
        tmin = getattr(self.heating, "return_temp_c", self.heating.room_temp_c)
        tmax = self.heating.inlet_temp_c
        r = min(max((temp_c - tmin) / max(1e-9, (tmax - tmin)), 0.0), 1.0)
        if r < 0.33: return (0.2 + 0.5 * (r/0.33), 0.2, 0.9 - 0.2 * (r/0.33))
        if r < 0.66: return (0.7 + 0.3 * ((r-0.33)/0.33), 0.2 + 0.2 * ((r-0.33)/0.33), 0.7 - 0.4 * ((r-0.33)/0.33))
        return (1.0, 0.4 + 0.5 * ((r-0.66)/0.34), 0.3 - 0.2 * ((r-0.66)/0.34))

    def draw_pipes(self):
        if self._pipe_display_list_dirty or self._pipe_display_list is None:
            self._rebuild_pipe_display_list()
        if self._pipe_display_list is not None:
            glCallList(self._pipe_display_list)

    def draw_pipe_dents(self):
        if self._dent_display_list_dirty or self._dent_display_list is None:
            self._rebuild_dent_display_list()
        if self._dent_display_list is not None:
            glCallList(self._dent_display_list)

    def _rebuild_pipe_display_list(self):
        if self._pipe_display_list is not None:
            glDeleteLists(self._pipe_display_list, 1)
            self._pipe_display_list = None
        self._pipe_display_list = glGenLists(1)
        glNewList(self._pipe_display_list, GL_COMPILE)
        self._draw_pipes_immediate()
        glEndList()
        self._pipe_display_list_dirty = False

    def _rebuild_dent_display_list(self):
        if self._dent_display_list is not None:
            glDeleteLists(self._dent_display_list, 1)
            self._dent_display_list = None
        self._dent_display_list = glGenLists(1)
        glNewList(self._dent_display_list, GL_COMPILE)
        self._draw_pipe_dents_immediate()
        glEndList()
        self._dent_display_list_dirty = False

    def _draw_pipes_immediate(self):
        if not self.tiles:
            return

        # Get temperature range for gradient calculation
        # Fallback values if heating spec is missing
        t_min = getattr(self.heating, "return_temp_c", self.heating.room_temp_c) if self.heating else 21.0
        t_max = self.heating.inlet_temp_c if self.heating else 45.0

        for i, part in enumerate(self.pipes):
            if not hasattr(part, "kind"):
                continue

            # Determine line width based on type (optional: keep bends thicker)
            if part.kind == "bend":
                glLineWidth(5)
            else:
                glLineWidth(3)

            glBegin(GL_LINE_STRIP)
            for p in part.points:
                if self.temperature_colors:
                    ratio = (p.temp_c - t_min) / max(1e-9, (t_max - t_min))
                    ratio = max(0.0, min(1.0, ratio))
                    g_val = 0.6 * (1.0 - ratio)
                    glColor3f(1.0, g_val, 0.0)
                elif part.kind == "bend":
                    glColor3f(1.0, 0.2, 0.2)
                else:
                    glColor3f(0.8, 0.5, 0.1)
                glVertex3f(p.x, p.y, p.z)
            glEnd()

            # Entry Point Marker (Green Dot)
            if i == 0 and part.points:
                start = part.points[0]
                glPointSize(10)
                glColor3f(0.0, 1.0, 0.0)
                glBegin(GL_POINTS)
                glVertex3f(start.x, start.y, start.z + 0.002)
                glEnd()

    def _draw_pipe_dents_immediate(self):
        if not self.tiles or not self.pipes:
            return

        surface_z = max(t.z1 for t in self.tiles) + 0.003
        pipe_d = self.heating.pipe_outer_diameter_m if self.heating else 0.016
        dent_factor = max(1.0, float(getattr(self.heating, "pipe_dent_width_factor", 1.35))) if self.heating else 1.35
        groove_d = pipe_d * dent_factor
        base_width = max(6.0, min(16.0, groove_d * 350.0))

        glDisable(GL_LIGHTING)
        glEnable(GL_BLEND)
        glEnable(GL_LINE_SMOOTH)
        glDepthMask(GL_FALSE)

        def draw_path(width, color, z_offset):
            glLineWidth(width)
            glColor4f(*color)
            for part in self.pipes:
                if not getattr(part, "points", None):
                    continue
                glBegin(GL_LINE_STRIP)
                for p in part.points:
                    glVertex3f(p.x, p.y, surface_z + z_offset)
                glEnd()

        # Wide shadow plus a narrow highlight gives the route a recessed,
        # grooved look without drawing the pipe itself.
        draw_path(base_width + 3.0, (0.01, 0.03, 0.07, 0.42), 0.000)
        draw_path(max(2.0, base_width * 0.45), (0.02, 0.05, 0.11, 0.58), 0.001)
        draw_path(max(1.0, base_width * 0.22), (0.72, 0.88, 1.00, 0.30), 0.002)

        glDepthMask(GL_TRUE)
        glDisable(GL_LINE_SMOOTH)
        glEnable(GL_LIGHTING)
                
    def _draw_tile_tops(self):
        # Transparent Top Faces (Glass Effect)
        glEnable(GL_BLEND)
        for t in self.tiles:
            if self.selected_tile is t:
                glColor4f(1.0, 0.85, 0.25, 0.7) # Yellow highlight semi-transparent
            elif t.is_fractional:
                glColor4f(0.45, 0.72, 1.00, 0.6) # Fractional blue semi-transparent
            else:
                glColor4f(0.10, 0.35, 0.95, 0.6) # Standard blue semi-transparent

            glBegin(GL_QUADS)
            glNormal3f(0, 0, 1)
            glVertex3f(t.x0, t.y0, t.z1); glVertex3f(t.x1, t.y0, t.z1)
            glVertex3f(t.x1, t.y1, t.z1); glVertex3f(t.x0, t.y1, t.z1)
            glEnd()

    def _draw_tile_edges(self):
        glDisable(GL_LIGHTING)
        glLineWidth(1.5)
        glColor3f(0.05, 0.05, 0.08)
        for t in self.tiles:
            glBegin(GL_LINE_LOOP)
            glVertex3f(t.x0, t.y0, t.z1 + 0.001)
            glVertex3f(t.x1, t.y0, t.z1 + 0.001)
            glVertex3f(t.x1, t.y1, t.z1 + 0.001)
            glVertex3f(t.x0, t.y1, t.z1 + 0.001)
            glEnd()
        glEnable(GL_LIGHTING)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.RightButton and self.tiles:
            picked = self._pick_tile_from_screen(event.x(), event.y())
            if picked is not None:
                self.selected_tile = picked
                self.update()
                QtCore.QTimer.singleShot(0, lambda tile=picked: self.tilePicked.emit(tile))
        elif event.button() == QtCore.Qt.LeftButton:
            self._left_press_pos = event.pos()
            self._left_press_tile = self._pick_tile_from_screen(event.x(), event.y())
            self._fractional_drag_candidate = self._fractional_drag_at(event.x(), event.y())
            self._fractional_drag = None
            self._left_drag_started = False
            self._last_pos = event.pos()

    def mouseMoveEvent(self, e):
        if self._left_press_pos and not self._left_drag_started:
            distance = (e.pos() - self._left_press_pos).manhattanLength()
            if distance < QtWidgets.QApplication.startDragDistance():
                return
            self._left_drag_started = True
            if self._fractional_drag_candidate:
                self._fractional_drag = self._fractional_drag_candidate

        if self._fractional_drag:
            self._emit_fractional_drag(e.x(), e.y())
            return
        if not self._last_pos: return
        dx = e.x() - self._last_pos.x()
        dy = e.y() - self._last_pos.y()
        self._user_moved_camera = True
        self.azimuth = (self.azimuth + dx * 0.4) % 360.0
        self.elevation = (self.elevation - dy * 0.4) % 360.0
        self._last_pos = e.pos()
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            if self._fractional_drag:
                self._emit_fractional_drag(event.x(), event.y(), True)
            elif not self._left_drag_started and self._left_press_tile is not None:
                tile = self._left_press_tile
                self.selected_tile = tile
                self.update()
                QtCore.QTimer.singleShot(0, lambda picked=tile: self.tileInspectRequested.emit(picked))
            self._fractional_drag = None
            self._fractional_drag_candidate = None
            self._left_press_pos = None
            self._left_press_tile = None
            self._left_drag_started = False
            self._last_pos = None

    def wheelEvent(self, e):
        self._user_moved_camera = True
        self.distance *= (0.92 ** (e.angleDelta().y() / 120.0))
        self.distance = max(2.0, min(40.0, self.distance))
        self.update()


class GLTileDetailView(QOpenGLWidget):
    def __init__(self, tile, pipe_parts=None, heating=None, parent=None):
        super().__init__(parent)
        self.tile = tile
        self.pipe_parts = pipe_parts or []
        self.heating = heating
        self.show_pipe = True
        self.azimuth = 38.0
        self.elevation = 32.0
        self._last_pos = None
        self.setMinimumSize(640, 480)
        self._fit_camera()

    def set_show_pipe(self, show):
        self.show_pipe = bool(show)
        self.update()

    def _fit_camera(self):
        width = max(self.tile.x1 - self.tile.x0, 0.01)
        depth = max(self.tile.y1 - self.tile.y0, 0.01)
        height = max(self.tile.z1 - self.tile.z0, 0.01)
        self.distance = max(width, depth, 4.0 * height) * 2.6

    def initializeGL(self):
        glClearColor(0.88, 0.89, 0.91, 1.0)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glEnable(GL_LINE_SMOOTH)
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glLightfv(GL_LIGHT0, GL_POSITION, (3.0, -4.0, 6.0, 1.0))
        glEnable(GL_COLOR_MATERIAL)
        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)

    def resizeGL(self, width, height):
        glViewport(0, 0, width, max(height, 1))
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(40.0, width / max(height, 1), 0.005, 100.0)
        glMatrixMode(GL_MODELVIEW)

    def _camera_vectors(self):
        width = self.tile.x1 - self.tile.x0
        depth = self.tile.y1 - self.tile.y0
        height = self.tile.z1 - self.tile.z0
        center = (0.5 * width, 0.5 * depth, 0.45 * height)
        azimuth = math.radians(self.azimuth)
        elevation = math.radians(self.elevation)
        eye = (
            center[0] + self.distance * math.cos(elevation) * math.cos(azimuth),
            center[1] + self.distance * math.cos(elevation) * math.sin(azimuth),
            center[2] + self.distance * math.sin(elevation),
        )
        up = (
            -math.sin(elevation) * math.cos(azimuth),
            -math.sin(elevation) * math.sin(azimuth),
            math.cos(elevation),
        )
        return eye, center, up

    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()
        eye, center, up = self._camera_vectors()
        gluLookAt(
            eye[0], eye[1], eye[2],
            center[0], center[1], center[2],
            up[0], up[1], up[2],
        )
        self._draw_tile()
        self._draw_pipe_route()
        self._draw_edges()

    def _draw_tile(self):
        width = self.tile.x1 - self.tile.x0
        depth = self.tile.y1 - self.tile.y0
        height = self.tile.z1 - self.tile.z0
        glColor3f(0.78, 0.80, 0.83)
        glBegin(GL_QUADS)
        glNormal3f(0.0, 0.0, -1.0)
        glVertex3f(0.0, 0.0, 0.0)
        glVertex3f(width, 0.0, 0.0)
        glVertex3f(width, depth, 0.0)
        glVertex3f(0.0, depth, 0.0)

        glNormal3f(0.0, 0.0, 1.0)
        glVertex3f(0.0, 0.0, height)
        glVertex3f(0.0, depth, height)
        glVertex3f(width, depth, height)
        glVertex3f(width, 0.0, height)

        glNormal3f(0.0, -1.0, 0.0)
        glVertex3f(0.0, 0.0, 0.0)
        glVertex3f(0.0, 0.0, height)
        glVertex3f(width, 0.0, height)
        glVertex3f(width, 0.0, 0.0)

        glNormal3f(0.0, 1.0, 0.0)
        glVertex3f(0.0, depth, 0.0)
        glVertex3f(width, depth, 0.0)
        glVertex3f(width, depth, height)
        glVertex3f(0.0, depth, height)

        glNormal3f(-1.0, 0.0, 0.0)
        glVertex3f(0.0, 0.0, 0.0)
        glVertex3f(0.0, depth, 0.0)
        glVertex3f(0.0, depth, height)
        glVertex3f(0.0, 0.0, height)

        glNormal3f(1.0, 0.0, 0.0)
        glVertex3f(width, 0.0, 0.0)
        glVertex3f(width, 0.0, height)
        glVertex3f(width, depth, height)
        glVertex3f(width, depth, 0.0)
        glEnd()

    def _clip_segment(self, a, b):
        x0, y0 = a.x, a.y
        x1, y1 = b.x, b.y
        dx, dy = x1 - x0, y1 - y0
        t0, t1 = 0.0, 1.0
        for p, q in (
            (-dx, x0 - self.tile.x0),
            (dx, self.tile.x1 - x0),
            (-dy, y0 - self.tile.y0),
            (dy, self.tile.y1 - y0),
        ):
            if abs(p) < 1e-12:
                if q < 0.0:
                    return None
                continue
            ratio = q / p
            if p < 0.0:
                if ratio > t1:
                    return None
                t0 = max(t0, ratio)
            else:
                if ratio < t0:
                    return None
                t1 = min(t1, ratio)
        if t1 <= t0:
            return None

        def point(t):
            temp = a.temp_c + (b.temp_c - a.temp_c) * t
            return (
                x0 + dx * t - self.tile.x0,
                y0 + dy * t - self.tile.y0,
                temp,
            )
        return point(t0), point(t1)

    def _visible_pipe_segments(self):
        segments = []
        for part in self.pipe_parts:
            points = getattr(part, "points", [])
            for a, b in zip(points[:-1], points[1:]):
                clipped = self._clip_segment(a, b)
                if clipped is not None:
                    segments.append(clipped)
        return segments

    def _temperature_color(self, temp_c):
        if not self.heating:
            return 0.85, 0.30, 0.12
        cold = getattr(self.heating, "return_temp_c", 20.0)
        hot = getattr(self.heating, "inlet_temp_c", cold + 1.0)
        ratio = max(0.0, min(1.0, (temp_c - cold) / max(hot - cold, 1e-9)))
        return 0.25 + 0.75 * ratio, 0.30 + 0.45 * (1.0 - ratio), 0.85 - 0.70 * ratio

    def _side_openings(self, segments):
        width = self.tile.x1 - self.tile.x0
        depth = self.tile.y1 - self.tile.y0
        epsilon = max(width, depth, 1.0) * 1e-6
        openings = {}
        for start, end in segments:
            for x, y, temp in (start, end):
                candidates = []
                if abs(x) <= epsilon:
                    candidates.append(("left", y, temp))
                if abs(x - width) <= epsilon:
                    candidates.append(("right", y, temp))
                if abs(y) <= epsilon:
                    candidates.append(("bottom", x, temp))
                if abs(y - depth) <= epsilon:
                    candidates.append(("top", x, temp))
                for side, tangent, point_temp in candidates:
                    key = (side, round(tangent, 6))
                    openings[key] = (side, tangent, point_temp)
        return list(openings.values())

    def _side_point(self, side, tangent, z, outward=0.0):
        width = self.tile.x1 - self.tile.x0
        depth = self.tile.y1 - self.tile.y0
        if side == "left":
            return -outward, tangent, z
        if side == "right":
            return width + outward, tangent, z
        if side == "bottom":
            return tangent, -outward, z
        return tangent, depth + outward, z

    def _draw_side_semicircle(self, side, tangent, radius, height, color, outward):
        glColor4f(*color)
        glBegin(GL_TRIANGLE_FAN)
        glVertex3f(*self._side_point(side, tangent, height, outward))
        for i in range(33):
            angle = math.pi + math.pi * (i / 32.0)
            offset = radius * math.cos(angle)
            z = height + radius * math.sin(angle)
            glVertex3f(*self._side_point(side, tangent + offset, z, outward))
        glEnd()

    def _draw_side_dents(self, segments, height, pipe_diameter, groove_factor):
        openings = self._side_openings(segments)
        if not openings:
            return
        pipe_radius = 0.5 * pipe_diameter
        groove_radius = max(pipe_radius * 1.15, 0.5 * pipe_diameter * groove_factor)
        groove_radius = min(groove_radius, max(0.48 * height, pipe_radius * 1.15))
        outward = max(1e-5, 0.002 * max(self.tile.x1 - self.tile.x0, self.tile.y1 - self.tile.y0))

        for side, tangent, temp in openings:
            self._draw_side_semicircle(
                side,
                tangent,
                groove_radius,
                height + 0.0005,
                (0.10, 0.11, 0.13, 0.96),
                outward,
            )

    def _extend_pipe_endpoint(self, point, extension):
        width = self.tile.x1 - self.tile.x0
        depth = self.tile.y1 - self.tile.y0
        x, y, temp = point
        epsilon = max(width, depth, 1.0) * 1e-6
        if abs(x) <= epsilon:
            x -= extension
        elif abs(x - width) <= epsilon:
            x += extension
        if abs(y) <= epsilon:
            y -= extension
        elif abs(y - depth) <= epsilon:
            y += extension
        return x, y, temp

    def _endpoint_boundary_side(self, point):
        width = self.tile.x1 - self.tile.x0
        depth = self.tile.y1 - self.tile.y0
        x, y = point[0], point[1]
        epsilon = max(width, depth, 1.0) * 1e-6
        if abs(x) <= epsilon:
            return "left", y
        if abs(x - width) <= epsilon:
            return "right", y
        if abs(y) <= epsilon:
            return "bottom", x
        if abs(y - depth) <= epsilon:
            return "top", x
        return None

    def _draw_pipe_open_end(self, side, tangent, center_z, radius, extension, color):
        inner_radius = 0.62 * radius
        glColor3f(*color)
        glBegin(GL_QUAD_STRIP)
        for i in range(33):
            angle = 2.0 * math.pi * (i / 32.0)
            tangent_offset = math.cos(angle)
            z_offset = math.sin(angle)
            glVertex3f(*self._side_point(
                side, tangent + radius * tangent_offset, center_z + radius * z_offset, extension
            ))
            glVertex3f(*self._side_point(
                side, tangent + inner_radius * tangent_offset, center_z + inner_radius * z_offset, extension
            ))
        glEnd()

        recess = max(0.0, extension - 0.35 * radius)
        glColor3f(0.025, 0.028, 0.035)
        glBegin(GL_TRIANGLE_FAN)
        glVertex3f(*self._side_point(side, tangent, center_z, recess))
        for i in range(33):
            angle = 2.0 * math.pi * (i / 32.0)
            glVertex3f(*self._side_point(
                side,
                tangent + inner_radius * math.cos(angle),
                center_z + inner_radius * math.sin(angle),
                recess,
            ))
        glEnd()

    def _draw_cylinder_between(self, quadric, start, end, radius):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        dz = end[2] - start[2]
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length <= 1e-9:
            return
        angle = math.degrees(math.acos(max(-1.0, min(1.0, dz / length))))
        axis_x, axis_y = -dy, dx
        glPushMatrix()
        glTranslatef(start[0], start[1], start[2])
        if abs(angle) > 1e-8:
            glRotatef(angle, axis_x, axis_y, 0.0)
        gluCylinder(quadric, radius, radius, length, 16, 1)
        glPopMatrix()

    def _draw_route_tube(
        self,
        segments,
        radius,
        center_z,
        extension,
        color_for_segment,
        draw_open_ends=False,
    ):
        if not segments:
            return
        quadric = gluNewQuadric()
        gluQuadricNormals(quadric, GLU_SMOOTH)
        open_ends = {}

        for start, end in segments:
            original_start = start
            original_end = end
            start_boundary = self._endpoint_boundary_side(original_start)
            end_boundary = self._endpoint_boundary_side(original_end)
            extended_start = self._extend_pipe_endpoint(original_start, extension)
            extended_end = self._extend_pipe_endpoint(original_end, extension)
            start_3d = (extended_start[0], extended_start[1], center_z)
            end_3d = (extended_end[0], extended_end[1], center_z)
            color = color_for_segment(original_start, original_end)
            glColor3f(*color)
            self._draw_cylinder_between(quadric, start_3d, end_3d, radius)

            for point, boundary in ((start_3d, start_boundary), (end_3d, end_boundary)):
                if boundary is not None:
                    if draw_open_ends:
                        side, tangent = boundary
                        open_ends[(side, round(tangent, 6))] = (side, tangent, color)
                    continue
                glPushMatrix()
                glTranslatef(*point)
                gluSphere(quadric, radius, 12, 8)
                glPopMatrix()

        gluDeleteQuadric(quadric)
        if draw_open_ends:
            for side, tangent, color in open_ends.values():
                self._draw_pipe_open_end(side, tangent, center_z, radius, extension, color)

    def _draw_pipe_tube(self, segments, height, pipe_diameter):
        radius = max(0.5 * pipe_diameter, 0.001)
        center_z = height - 0.55 * radius
        self._draw_route_tube(
            segments,
            radius,
            center_z,
            1.35 * radius,
            lambda start, end: self._temperature_color(0.5 * (start[2] + end[2])),
            True,
        )

    def _draw_groove_channel(self, segments, height, pipe_diameter, groove_factor):
        pipe_radius = max(0.5 * pipe_diameter, 0.001)
        groove_radius = max(1.18 * pipe_radius, 0.5 * pipe_diameter * groove_factor)
        center_z = height - 0.82 * groove_radius
        self._draw_route_tube(
            segments,
            groove_radius,
            center_z,
            0.0,
            lambda _start, _end: (0.12, 0.13, 0.15),
        )

    def _draw_pipe_route(self):
        segments = self._visible_pipe_segments()
        if not segments:
            return
        height = self.tile.z1 - self.tile.z0
        pipe_diameter = getattr(self.heating, "pipe_outer_diameter_m", 0.016) if self.heating else 0.016
        groove_factor = max(1.0, float(getattr(self.heating, "pipe_dent_width_factor", 1.35))) if self.heating else 1.35

        glDisable(GL_LIGHTING)
        glDepthMask(GL_FALSE)
        self._draw_side_dents(segments, height, pipe_diameter, groove_factor)
        glDepthMask(GL_TRUE)
        glEnable(GL_LIGHTING)
        if self.show_pipe:
            self._draw_pipe_tube(segments, height, pipe_diameter)
        else:
            self._draw_groove_channel(segments, height, pipe_diameter, groove_factor)

    def _draw_edges(self):
        width = self.tile.x1 - self.tile.x0
        depth = self.tile.y1 - self.tile.y0
        height = self.tile.z1 - self.tile.z0
        glDisable(GL_LIGHTING)
        glLineWidth(1.5)
        glColor3f(0.10, 0.11, 0.13)
        for z in (0.0, height):
            glBegin(GL_LINE_LOOP)
            glVertex3f(0.0, 0.0, z)
            glVertex3f(width, 0.0, z)
            glVertex3f(width, depth, z)
            glVertex3f(0.0, depth, z)
            glEnd()
        glBegin(GL_LINES)
        for x, y in ((0.0, 0.0), (width, 0.0), (width, depth), (0.0, depth)):
            glVertex3f(x, y, 0.0)
            glVertex3f(x, y, height)
        glEnd()
        glEnable(GL_LIGHTING)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._last_pos = event.pos()

    def mouseMoveEvent(self, event):
        if self._last_pos is None:
            return
        dx = event.x() - self._last_pos.x()
        dy = event.y() - self._last_pos.y()
        self.azimuth = (self.azimuth + dx * 0.5) % 360.0
        self.elevation = (self.elevation - dy * 0.5) % 360.0
        self._last_pos = event.pos()
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._last_pos = None

    def mouseDoubleClickEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.azimuth = 38.0
            self.elevation = 32.0
            self._fit_camera()
            self.update()

    def wheelEvent(self, event):
        self.distance *= 0.90 ** (event.angleDelta().y() / 120.0)
        minimum = max(self.tile.x1 - self.tile.x0, self.tile.y1 - self.tile.y0, 0.05) * 0.45
        self.distance = max(minimum, min(50.0, self.distance))
        self.update()
