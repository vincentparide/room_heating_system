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
    partial_x_side: str = "right"
    partial_y_side: str = "top"
    full_tile_offset_x_m: float = 0.0
    full_tile_offset_y_m: float = 0.0
    partial_x_positions: List[int] = field(default_factory=list)
    partial_y_positions: List[int] = field(default_factory=list)

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
    pipe_dent_width_factor: float = 1.35
    pipe_connection_extension_m: float = 0.15
    pipe_connection_spacing_m: float = 0.10
    pipe_spacing_m: float = 0.10
    edge_cover_m: float = 0.05
    top_cover_m: float = 0.010
    target_heat_flux_w_m2: float = 100.0
    design_heat_flux_w_m2: float = 100.0
    water_delta_t_k: float = 5.0
    floor_covering: str = "ceramic_tiles"
    screed_type: str = "cement"
    en1264_pipe_type: str = "pex_16x2"
    insulation_level: str = "standard"
    building_level: str = "modern"
    inlet_temp_c: float = 45.0
    return_temp_c: float = 40.0
    room_temp_c: float = 21.0
    mean_water_temp_c: float = 41.5
    floor_surface_temp_c: float = 0.0
    total_heat_load_w: float = 0.0
    mass_flow_kg_h: float = 0.0
    calculated_water_delta_t_k: float = 0.0
    water_density_kg_m3: float = 998.0
    volume_flow_m3_h: float = 0.0
    volume_flow_l_min: float = 0.0
    estimated_pipe_length_m: float = 0.0
    en1264_b_coefficient: float = 0.0
    equivalent_heat_transmission_w_m2_k: float = 0.0
    log_mean_delta_theta_k: float = 0.0
    characteristic_exponent: float = 1.0
    overall_heat_transfer_w_m2_k: float = 0.0
    heat_transfer_area_m2: float = 0.0
    mass_flow_kg_s: float = 0.0
    temperature_decay_factor: float = 0.0
    en1264_status: str = ""
    inlet_tile_index: int = 0
    outlet_tile_index: int = 0
    connection_direction: str = "left"
    pipe_orientation: str = "auto"
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
    pipe_entry_distance_m: float = 0.0
    pipe_exit_distance_m: float = 0.0
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
    inlet_tile_id: str = ""
    outlet_tile_id: str = ""
    pipe_orientation: str = ""
