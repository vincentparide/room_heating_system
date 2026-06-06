import math
from dataclasses import dataclass

WATER_CP_J_KG_K = 4190.0
FLOOR_SURFACE_HEAT_TRANSFER_W_M2_K = 8.92
CHARACTERISTIC_EXPONENT = 1.0
EN1264_MAX_DESIGN_WATER_DROP_K = 5.0


@dataclass(frozen=True)
class EN1264Option:
    key: str
    label: str
    value: float


@dataclass(frozen=True)
class EN1264DesignResult:
    area_m2: float
    target_heat_flux_w_m2: float
    total_heat_load_w: float
    b_coefficient: float
    mean_water_temp_c: float
    supply_temp_c: float
    return_temp_c: float
    water_delta_t_k: float
    floor_surface_temp_c: float
    mass_flow_kg_h: float
    water_density_kg_m3: float
    volume_flow_m3_h: float
    volume_flow_l_min: float
    estimated_pipe_length_m: float
    equivalent_heat_transmission_w_m2_k: float
    log_mean_delta_theta_k: float
    characteristic_exponent: float
    overall_heat_transfer_w_m2_k: float
    heat_transfer_area_m2: float
    mass_flow_kg_s: float
    temperature_decay_factor: float
    floor_covering_label: str
    screed_label: str
    pipe_label: str
    insulation_label: str
    building_label: str
    status: str


FLOOR_COVERINGS = (
    EN1264Option("ceramic_tiles", "Ceramic tiles (R=0.05 m2K/W)", 0.05),
    EN1264Option("natural_stone", "Natural stone (R=0.06 m2K/W)", 0.06),
    EN1264Option("laminate", "Laminate / engineered wood (R=0.10 m2K/W)", 0.10),
    EN1264Option("solid_wood", "Solid wood flooring (R=0.13 m2K/W)", 0.13),
    EN1264Option("thin_carpet", "Thin carpet (R=0.15 m2K/W)", 0.15),
    EN1264Option("thick_carpet", "Thick carpet (R=0.20 m2K/W)", 0.20),
)

SCREED_TYPES = (
    EN1264Option("cement", "Cement screed (lambda=1.2 W/mK)", 1.2),
    EN1264Option("anhydrite", "Anhydrite screed (lambda=1.6 W/mK)", 1.6),
    EN1264Option("lightweight", "Lightweight concrete (lambda=0.8 W/mK)", 0.8),
    EN1264Option("dry_board", "Dry screed board (lambda=0.4 W/mK)", 0.4),
)

PIPE_TYPES = (
    EN1264Option("pex_16x2", "PEX 16x2 mm", 0.016),
    EN1264Option("pex_17x2", "PEX 17x2 mm", 0.017),
    EN1264Option("pex_20x2", "PEX 20x2 mm", 0.020),
    EN1264Option("multilayer_16x2", "Multilayer composite 16x2 mm", 0.016),
)

INSULATION_LEVELS = (
    EN1264Option("high", "High insulation below pipes (R=2.0 m2K/W)", 2.0),
    EN1264Option("standard", "Standard insulation below pipes (R=1.0 m2K/W)", 1.0),
    EN1264Option("minimum", "Minimum insulation below pipes (R=0.75 m2K/W)", 0.75),
    EN1264Option("none", "None below pipes (not recommended)", 0.30),
)

BUILDING_LEVELS = (
    EN1264Option("modern", "Modern building (KfW 55 / EnEV 2016)", 0.85),
    EN1264Option("good", "Good building (post 2000)", 1.0),
    EN1264Option("average", "Average building (1990-2005)", 1.15),
    EN1264Option("old", "Old building (pre 1990)", 1.30),
)


def options_for_combo(options):
    return [(option.label, option.key) for option in options]


def option_by_key(options, key):
    for option in options:
        if option.key == key:
            return option
    return options[0]


def label_for_key(options, key):
    return option_by_key(options, key).label


def _clamp(value, low, high):
    return max(low, min(high, value))


def water_density_kg_m3(temp_c):
    # Empirical density of pure water near atmospheric pressure, valid for ordinary heating ranges.
    t = _clamp(float(temp_c), 0.0, 100.0)
    return 1000.0 * (
        1.0 - ((t + 288.9414) / (508929.2 * (t + 68.12963))) * (t - 3.9863) ** 2
    )


def _pipe_wall_resistance_m2_k_w(pipe_key, outer_diameter_m):
    wall_m = 0.002
    inner_d = max(outer_diameter_m - 2.0 * wall_m, 0.001)
    conductivity = 0.55 if "multilayer" in pipe_key else 0.35
    return outer_diameter_m * math.log(max(outer_diameter_m / inner_d, 1.0001)) / (2.0 * conductivity)


def calculate_equivalent_heat_transmission_coefficient(h):
    floor = option_by_key(FLOOR_COVERINGS, getattr(h, "floor_covering", "ceramic_tiles"))
    screed = option_by_key(SCREED_TYPES, getattr(h, "screed_type", "cement"))
    pipe = option_by_key(PIPE_TYPES, getattr(h, "en1264_pipe_type", "pex_16x2"))

    spacing_m = max(float(getattr(h, "pipe_spacing_m", 0.10)), 0.01)
    top_cover_m = max(float(getattr(h, "top_cover_m", 0.010)), 0.001)
    pipe_d_m = max(float(getattr(h, "pipe_outer_diameter_m", pipe.value)), 0.001)
    screed_k = max(screed.value, 0.05)

    surface_r = 1.0 / FLOOR_SURFACE_HEAT_TRANSFER_W_M2_K
    cover_r = top_cover_m / screed_k
    spreading_r = max(spacing_m - pipe_d_m, 0.0) / (2.0 * screed_k)
    pipe_wall_r = _pipe_wall_resistance_m2_k_w(pipe.key, pipe_d_m)
    upward_r = max(surface_r + floor.value + cover_r + spreading_r + pipe_wall_r, 1e-6)
    return max(1.0 / upward_r, 0.1)


def calculate_overall_heat_transfer_coefficient(h):
    return calculate_equivalent_heat_transmission_coefficient(h)


def calculate_log_mean_delta_theta(supply_temp_c, return_temp_c, room_temp_c):
    supply_excess = max(float(supply_temp_c) - float(room_temp_c), 1e-9)
    return_excess = max(float(return_temp_c) - float(room_temp_c), 1e-9)
    if abs(supply_excess - return_excess) < 1e-9:
        return supply_excess
    return (supply_excess - return_excess) / math.log(supply_excess / return_excess)


def solve_supply_return_from_log_mean(delta_theta_h_k, water_drop_k, room_temp_c):
    delta_theta = max(float(delta_theta_h_k), 1e-6)
    water_drop = max(float(water_drop_k), 0.0)
    room_temp = float(room_temp_c)

    if water_drop <= 1e-9:
        temp = room_temp + delta_theta
        return temp, temp

    exponent = min(max(water_drop / delta_theta, 1e-9), 50.0)
    ratio = math.exp(exponent)
    return_excess = water_drop / max(ratio - 1.0, 1e-9)
    supply_excess = return_excess + water_drop
    return room_temp + supply_excess, room_temp + return_excess


def calculate_temperature_profile_factor(supply_temp_c, return_temp_c, room_temp_c):
    supply_excess = max(float(supply_temp_c) - float(room_temp_c), 1e-9)
    return_excess = max(float(return_temp_c) - float(room_temp_c), 1e-9)
    return max(math.log(supply_excess / return_excess), 1e-9)


def calculate_downward_loss_density(log_mean_delta_theta_k, h):
    insulation = option_by_key(INSULATION_LEVELS, getattr(h, "insulation_level", "standard"))
    downward_r = max(insulation.value + 0.17, 1e-6)
    return max(float(log_mean_delta_theta_k) / downward_r, 0.0)


def calculate_en1264_design(h, area_m2, pipe_length_m=None):
    area = max(float(area_m2), 0.01)
    spacing_cm = max(float(getattr(h, "pipe_spacing_m", 0.10)) * 100.0, 1.0)
    target_q = max(float(getattr(h, "target_heat_flux_w_m2", 100.0)), 1.0)
    water_drop = max(float(getattr(h, "water_delta_t_k", 7.0)), 0.1)
    room_temp = float(getattr(h, "room_temp_c", 21.0))

    floor = option_by_key(FLOOR_COVERINGS, getattr(h, "floor_covering", "ceramic_tiles"))
    screed = option_by_key(SCREED_TYPES, getattr(h, "screed_type", "cement"))
    pipe = option_by_key(PIPE_TYPES, getattr(h, "en1264_pipe_type", "pex_16x2"))
    insulation = option_by_key(INSULATION_LEVELS, getattr(h, "insulation_level", "standard"))
    building = option_by_key(BUILDING_LEVELS, getattr(h, "building_level", "modern"))

    design_q = target_q * _clamp(building.value, 0.85, 1.30)
    kh = calculate_equivalent_heat_transmission_coefficient(h)
    exponent = CHARACTERISTIC_EXPONENT
    required_delta_theta_h = (design_q / kh) ** (1.0 / exponent)
    supply, return_temp = solve_supply_return_from_log_mean(required_delta_theta_h, water_drop, room_temp)
    calculated_drop = supply - return_temp
    log_mean_delta_theta = calculate_log_mean_delta_theta(supply, return_temp, room_temp)
    profile_factor = calculate_temperature_profile_factor(supply, return_temp, room_temp)

    downward_loss_q = calculate_downward_loss_density(log_mean_delta_theta, h)
    total_heat_load = (design_q + downward_loss_q) * area
    mean_water_temp = room_temp + log_mean_delta_theta
    surface_delta = (design_q / FLOOR_SURFACE_HEAT_TRANSFER_W_M2_K) ** (1.0 / 1.1)
    floor_surface = room_temp + surface_delta

    mass_flow_kg_s = total_heat_load / max(WATER_CP_J_KG_K * calculated_drop, 1e-9)
    mass_flow_kg_h = mass_flow_kg_s * 3600.0
    density = water_density_kg_m3(0.5 * (supply + return_temp))
    volume_flow_m3_h = mass_flow_kg_h / max(density, 1e-9)
    volume_flow_l_min = volume_flow_m3_h * 1000.0 / 60.0
    estimated_length = pipe_length_m if pipe_length_m is not None else (area * 1.15) / (spacing_cm / 100.0)

    status_items = []
    if floor_surface > 29.0:
        status_items.append("Floor surface above 29.0 °C EN 1264 occupied-area comfort limit")
    if water_drop > EN1264_MAX_DESIGN_WATER_DROP_K:
        status_items.append("Water temperature drop above EN 1264 limit-curve range sigma <= 5 K")
    if floor.value > 0.15:
        status_items.append("Floor covering resistance R_lambda,B above 0.15 m²K/W should be avoided where possible")
    if supply > 55.0:
        status_items.append("Supply temperature above typical floor-heating design range")
    status = "; ".join(status_items) if status_items else "OK"

    return EN1264DesignResult(
        area,
        design_q,
        total_heat_load,
        kh,
        mean_water_temp,
        supply,
        return_temp,
        calculated_drop,
        floor_surface,
        mass_flow_kg_h,
        density,
        volume_flow_m3_h,
        volume_flow_l_min,
        float(estimated_length or 0.0),
        kh,
        log_mean_delta_theta,
        exponent,
        kh,
        area,
        mass_flow_kg_s,
        profile_factor,
        floor.label,
        screed.label,
        pipe.label,
        insulation.label,
        building.label,
        status,
    )


def apply_en1264_design(h, area_m2, pipe_length_m=None):
    result = calculate_en1264_design(h, area_m2, pipe_length_m)
    h.inlet_temp_c = result.supply_temp_c
    h.return_temp_c = result.return_temp_c
    h.design_heat_flux_w_m2 = result.target_heat_flux_w_m2
    h.mean_water_temp_c = result.mean_water_temp_c
    h.floor_surface_temp_c = result.floor_surface_temp_c
    h.total_heat_load_w = result.total_heat_load_w
    h.mass_flow_kg_h = result.mass_flow_kg_h
    h.calculated_water_delta_t_k = result.supply_temp_c - result.return_temp_c
    h.water_density_kg_m3 = result.water_density_kg_m3
    h.volume_flow_m3_h = result.volume_flow_m3_h
    h.volume_flow_l_min = result.volume_flow_l_min
    h.estimated_pipe_length_m = result.estimated_pipe_length_m
    h.en1264_b_coefficient = result.b_coefficient
    h.equivalent_heat_transmission_w_m2_k = result.equivalent_heat_transmission_w_m2_k
    h.log_mean_delta_theta_k = result.log_mean_delta_theta_k
    h.characteristic_exponent = result.characteristic_exponent
    h.overall_heat_transfer_w_m2_k = result.overall_heat_transfer_w_m2_k
    h.heat_transfer_area_m2 = result.heat_transfer_area_m2
    h.mass_flow_kg_s = result.mass_flow_kg_s
    h.temperature_decay_factor = result.temperature_decay_factor
    h.en1264_status = result.status
    h.recommended_pipe = result.pipe_label
    return result
