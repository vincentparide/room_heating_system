from dataclasses import dataclass, field
from typing import List

@dataclass
class RoomSpec:
    length_m: float = 5.0
    width_m: float = 4.0

@dataclass
class TileSpec:
    length_m: float = 0.6
    width_m: float = 0.6
    thickness_m: float = 0.04

@dataclass
class SupportSpec:
    plate_radius_m: float = 0.05
    plate_height_m: float = 0.002
    column_radius_m: float = 0.002
    column_height_m: float = 0.15
    cylinder_detail: int = 24

@dataclass
class HeatingSpec:
    pipe_layout: str = "meander"
    pipe_outer_diameter_m: float = 0.016
    pipe_spacing_m: float = 0.10
    edge_cover_m: float = 0.05
    top_cover_m: float = 0.010
    inlet_temp_c: float = 45.0
    room_temp_c: float = 21.0
    heat_loss_per_m_k: float = 0.22
    bend_radius_factor: float = 5.0
    recommended_pipe: str = "PEX-AL-PEX 16x2 mm"

@dataclass
class PipePoint:
    x: float
    y: float
    z: float
    temp_c: float = 0.0

@dataclass
class PipePart:
    part_id: str
    kind: str
    tile_id: str
    points: List[PipePoint] = field(default_factory=list)
    qr_payload: str = ""

@dataclass
class Tile:
    x0: float
    y0: float
    x1: float
    y1: float
    z0: float
    z1: float
    is_fractional: bool
    tile_id: str
    qr_payload: str = ""
    pipe_points: List[PipePoint] = field(default_factory=list)
    pipe_parts: List[PipePart] = field(default_factory=list)
    pipe_length_m: float = 0.0
    pipe_inlet_temp_c: float = 0.0
    pipe_outlet_temp_c: float = 0.0

@dataclass
class Support:
    cx: float
    cy: float
    z0: float

@dataclass
class RoomCircuit:
    pipe_points: List[PipePoint] = field(default_factory=list)
    pipe_parts: List[PipePart] = field(default_factory=list)
    total_length_m: float = 0.0
    inlet_temp_c: float = 0.0
    outlet_temp_c: float = 0.0