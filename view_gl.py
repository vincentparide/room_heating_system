# view_gl.py
import math
from PyQt5 import QtCore
from PyQt5.QtWidgets import QOpenGLWidget
from OpenGL.GL import *
from OpenGL.GLU import *

class GLRoomView(QOpenGLWidget):
    tilePicked = QtCore.pyqtSignal(object)

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

        self.azimuth = 45.0
        self.elevation = 30.0
        self.distance = 9.0
        self._last_pos = None
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
        self.update()
        
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

    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()

        if not self.room:
            return

        cx = self.room.length_m * 0.5
        cy = self.room.width_m * 0.5
        cz = 0.0

        az = math.radians(self.azimuth)
        el = math.radians(self.elevation)
        
        cam_x = cx + self.distance * math.cos(el) * math.cos(az)
        cam_y = cy + self.distance * math.cos(el) * math.sin(az)
        cam_z = cz + self.distance * math.sin(el)

        up_x = -math.sin(el) * math.cos(az)
        up_y = -math.sin(el) * math.sin(az)
        up_z = math.cos(el)
        
        gluLookAt(cam_x, cam_y, cam_z, cx, cy, cz, up_x, up_y, up_z)

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
        tmin = self.heating.room_temp_c
        tmax = self.heating.inlet_temp_c
        r = min(max((temp_c - tmin) / max(1e-9, (tmax - tmin)), 0.0), 1.0)
        if r < 0.33: return (0.2 + 0.5 * (r/0.33), 0.2, 0.9 - 0.2 * (r/0.33))
        if r < 0.66: return (0.7 + 0.3 * ((r-0.33)/0.33), 0.2 + 0.2 * ((r-0.33)/0.33), 0.7 - 0.4 * ((r-0.33)/0.33))
        return (1.0, 0.4 + 0.5 * ((r-0.66)/0.34), 0.3 - 0.2 * ((r-0.66)/0.34))

    def draw_pipes(self):
        if not self.tiles:
            return

        # Get temperature range for gradient calculation
        # Fallback values if heating spec is missing
        t_min = self.heating.room_temp_c if self.heating else 21.0
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
            x = event.x()
            y = self.height() - event.y()
            model = glGetDoublev(GL_MODELVIEW_MATRIX)
            proj = glGetDoublev(GL_PROJECTION_MATRIX)
            view = glGetIntegerv(GL_VIEWPORT)
            near = gluUnProject(x, y, 0.0, model, proj, view)
            far = gluUnProject(x, y, 1.0, model, proj, view)
            z_plane = self.tiles[0].z1
            t = (z_plane - near[2]) / (far[2] - near[2])
            px = near[0] + (far[0] - near[0]) * t
            py = near[1] + (far[1] - near[1]) * t
            for tile in self.tiles:
                if tile.x0 <= px <= tile.x1 and tile.y0 <= py <= tile.y1:
                    self.selected_tile = tile
                    self.tilePicked.emit(tile)
                    self.update()
                    return
        elif event.button() == QtCore.Qt.LeftButton:
            self._last_pos = event.pos()

    def mouseMoveEvent(self, e):
        if not self._last_pos: return
        dx = e.x() - self._last_pos.x()
        dy = e.y() - self._last_pos.y()
        self.azimuth = (self.azimuth + dx * 0.4) % 360.0
        self.elevation = (self.elevation - dy * 0.4) % 360.0
        self._last_pos = e.pos()
        self.update()

    def wheelEvent(self, e):
        self.distance *= (0.92 ** (e.angleDelta().y() / 120.0))
        self.distance = max(2.0, min(40.0, self.distance))
        self.update()
