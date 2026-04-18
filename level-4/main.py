import sys
import json
import math

sys.stdout.reconfigure(encoding="utf-8")

# ── Load race data ─────────────────────────────────────────────────────────────
race_data = json.load(open("level-4/level4.json"))

track_segments  = race_data["track"]["segments"]
crawl_constant  = race_data["car"]["crawl_constant_m/s"]
max_speed       = race_data["car"]["max_speed_m/s"]
brake_decel     = race_data["car"]["brake_m/se2"]
accel           = race_data["car"]["accel_m/se2"]
num_laps        = race_data["race"]["laps"]
tank_capacity   = race_data["car"]["fuel_tank_capacity_l"]
initial_fuel    = race_data["car"]["initial_fuel_l"]
refuel_rate     = race_data["race"]["pit_refuel_rate_l/s"]
fuel_soft_cap   = race_data["race"]["fuel_soft_cap_limit_l"]
pit_base_time   = race_data["race"]["base_pit_stop_time_s"]
pit_tyre_time   = race_data["race"]["pit_tyre_swap_time_s"]
pit_exit_speed  = race_data["race"]["pit_exit_speed_m/s"]

weather_conditions = race_data["weather"]["conditions"]
tyre_props         = race_data["tyres"]["properties"]
available_sets     = race_data["available_sets"]

K_BASE = 0.0005
K_DRAG = 0.0000000015

seg_by_id      = {seg["id"]: seg for seg in track_segments}
max_segment_id = max(seg_by_id.keys())

# ── Tyre inventory ─────────────────────────────────────────────────────────────
tyre_inventory = {}
for entry in available_sets:
    tyre_inventory[entry["compound"]] = list(entry["ids"])

def get_next_tyre_id(compound):
    ids = tyre_inventory.get(compound, [])
    if ids:
        return ids.pop(0)
    return None

def compound_available(compound):
    return len(tyre_inventory.get(compound, [])) > 0

def any_tyre_available():
    return any(len(ids) > 0 for ids in tyre_inventory.values())

# ── Weather timeline ───────────────────────────────────────────────────────────
def build_weather_timeline(total_s):
    timeline, t = [], 0.0
    while t < total_s + 20000:
        for cond in weather_conditions:
            timeline.append((t, t + cond["duration_s"], cond))
            t += cond["duration_s"]
    return timeline

def get_weather_at(elapsed_s, timeline):
    for (start, end, cond) in timeline:
        if start <= elapsed_s < end:
            return cond
    return timeline[-1][2]

# ── Weather/tyre key maps ──────────────────────────────────────────────────────
WEATHER_FRICTION_KEY = {
    "dry":        "dry_friction_multiplier",
    "cold":       "cold_friction_multiplier",
    "light_rain": "light_rain_friction_multiplier",
    "heavy_rain": "heavy_rain_friction_multiplier",
}
WEATHER_DEGRAD_KEY = {
    "dry":        "dry_degradation",
    "cold":       "cold_degradation",
    "light_rain": "light_rain_degradation",
    "heavy_rain": "heavy_rain_degradation",
}

BASE_FRICTION = {
    "Soft": 1.8, "Medium": 1.7, "Hard": 1.6,
    "Intermediate": 1.2, "Wet": 1.1
}

# ── Tyre physics ───────────────────────────────────────────────────────────────
def get_friction(compound, tyre_life, weather_name):
    degradation  = 1.0 - tyre_life
    base         = BASE_FRICTION[compound]
    weather_mult = tyre_props[compound][WEATHER_FRICTION_KEY[weather_name]]
    return (base - degradation) * weather_mult

def degrad_per_segment(compound, weather_name, seg, speed, radius=None):
    rate       = tyre_props[compound][WEATHER_DEGRAD_KEY[weather_name]]
    K_STRAIGHT = 0.0000166
    K_BRAKING  = 0.0398
    K_CORNER   = 0.000265
    if seg["type"] == "corner":
        return K_CORNER * (speed**2 / radius) * rate
    else:
        straight_deg = rate * seg["length_m"] * K_STRAIGHT
        brake_deg    = ((max_speed / 100)**2 - (speed / 100)**2) * K_BRAKING * rate
        return straight_deg + brake_deg

def max_corner_speed_from_friction(friction_val, radius):
    return math.sqrt(max(0, friction_val) * 9.8 * radius) + crawl_constant

def best_compound_for_weather(weather_name, must_have_inventory=True):
    """Return best available compound for this weather. If must_have_inventory
    is True, only consider compounds with sets remaining. Falls back to current
    compound (passed via global) if nothing is available."""
    best, best_mult = None, -1
    for compound in tyre_props:
        if must_have_inventory and not compound_available(compound):
            continue
        mult = tyre_props[compound][WEATHER_FRICTION_KEY[weather_name]]
        if mult > best_mult:
            best_mult = mult
            best = compound
    return best  # may be None if inventory exhausted

def safe_best_compound(weather_name, fallback_compound):
    """Always returns a valid compound string — falls back to current if needed."""
    best = best_compound_for_weather(weather_name, must_have_inventory=True)
    return best if best is not None else fallback_compound

# ── Fuel helpers ───────────────────────────────────────────────────────────────
def fuel_used_phase(v_i, v_f, dist):
    avg = (v_i + v_f) / 2
    return (K_BASE + K_DRAG * avg**2) * dist

def estimate_fuel_per_lap(compound, weather_name):
    total = 0.0
    for seg in track_segments:
        if seg["type"] == "corner":
            spd = max_corner_speed_from_friction(
                tyre_props[compound][WEATHER_FRICTION_KEY[weather_name]], seg["radius_m"])
            total += fuel_used_phase(spd, spd, seg["length_m"])
        else:
            total += fuel_used_phase(max_speed * 0.6, max_speed, seg["length_m"])
    return total

# ── Segment time estimate ──────────────────────────────────────────────────────
def segment_time_estimate(length, v_entry, v_target, v_exit, weather):
    eff_accel = accel * weather["acceleration_multiplier"]
    eff_brake = brake_decel * weather["deceleration_multiplier"]

    accel_dist  = max(0.0, (v_target**2 - v_entry**2) / (2 * eff_accel)) if v_target > v_entry else 0.0
    brake_dist  = max(0.0, (v_target**2 - v_exit**2)  / (2 * eff_brake)) if v_target > v_exit  else 0.0
    accel_dist  = min(accel_dist, max(0.0, length - brake_dist))
    cruise_dist = max(0.0, length - accel_dist - brake_dist)

    t = 0.0
    if accel_dist > 0 and eff_accel > 0:
        t += (v_target - v_entry) / eff_accel
    if cruise_dist > 0 and v_target > 0:
        t += cruise_dist / v_target
    if brake_dist > 0 and eff_brake > 0:
        t += (v_target - v_exit) / eff_brake
    return max(t, length / max(v_target, 1.0))

# ── Simulation setup ───────────────────────────────────────────────────────────
ESTIMATED_RACE_TIME = 65000
weather_timeline = build_weather_timeline(ESTIMATED_RACE_TIME)

elapsed_time  = 0.0
current_fuel  = initial_fuel
tyre_life     = 1.0

initial_weather = get_weather_at(0.0, weather_timeline)

# Capture initial tyre ID before inventory is mutated
_best_start_entry = max(
    available_sets,
    key=lambda e: tyre_props[e["compound"]][WEATHER_FRICTION_KEY[initial_weather["condition"]]]
)
_initial_tyre_id = _best_start_entry["ids"][0]
current_compound  = _best_start_entry["compound"]
current_tyre_id   = get_next_tyre_id(current_compound)

print(f"Starting on {current_compound} (ID {current_tyre_id}) | weather: {initial_weather['condition']}")

TYRE_LIFE_DANGER  = 0.20
FUEL_RESERVE_LAPS = 1.1

laps_out = []

# ── Main simulation loop ───────────────────────────────────────────────────────
for lap_num in range(1, num_laps + 1):
    lap_segments_out = []
    lap_fuel_used    = 0.0
    lap_tyre_wear    = 0.0

    for seg in track_segments:
        weather   = get_weather_at(elapsed_time, weather_timeline)
        w_name    = weather["condition"]
        eff_brake = brake_decel * weather["deceleration_multiplier"]
        friction  = get_friction(current_compound, tyre_life, w_name)

        if seg["type"] == "corner":
            speed = max(max_corner_speed_from_friction(friction, seg["radius_m"]), crawl_constant)
            t     = seg["length_m"] / speed
            elapsed_time += t

            wear      = degrad_per_segment(current_compound, w_name, seg, speed, seg["radius_m"])
            lap_tyre_wear += wear
            tyre_life = max(0.0, tyre_life - wear)

            lap_fuel_used += fuel_used_phase(speed, speed, seg["length_m"])
            lap_segments_out.append({"id": seg["id"], "type": "corner"})

        else:
            sid    = seg["id"]
            length = seg["length_m"]

            prev_id  = ((sid - 2) % max_segment_id) + 1
            prev_seg = seg_by_id[prev_id]
            if prev_seg["type"] == "corner":
                entry_speed = max_corner_speed_from_friction(
                    get_friction(current_compound, tyre_life, w_name), prev_seg["radius_m"])
            else:
                entry_speed = min(max_speed, pit_exit_speed)

            next_id  = (sid % max_segment_id) + 1
            next_seg = seg_by_id[next_id]
            if next_seg["type"] == "corner":
                exit_speed = max_corner_speed_from_friction(
                    get_friction(current_compound, tyre_life, w_name), next_seg["radius_m"])
            else:
                exit_speed = max_speed

            b_dist = min(max(0.0, (max_speed**2 - exit_speed**2) / (2 * eff_brake)), length)
            t      = segment_time_estimate(length, entry_speed, max_speed, exit_speed, weather)
            elapsed_time += t

            eff_accel = accel * weather["acceleration_multiplier"]
            a_dist    = min(max(0.0, (max_speed**2 - entry_speed**2) / (2 * eff_accel)),
                           max(0.0, length - b_dist))
            c_dist    = max(0.0, length - a_dist - b_dist)

            lap_fuel_used += fuel_used_phase(entry_speed, max_speed, a_dist)
            lap_fuel_used += fuel_used_phase(max_speed, max_speed, c_dist)
            lap_fuel_used += fuel_used_phase(max_speed, exit_speed, b_dist)

            wear      = degrad_per_segment(current_compound, w_name, seg, exit_speed)
            lap_tyre_wear += wear
            tyre_life = max(0.0, tyre_life - wear)

            lap_segments_out.append({
                "id":                        sid,
                "type":                      "straight",
                "target_m/s":                round(max_speed, 4),
                "brake_start_m_before_next": round(b_dist, 4)
            })

    current_fuel -= lap_fuel_used

    # ── Pit decision ───────────────────────────────────────────────────────────
    next_weather    = get_weather_at(elapsed_time, weather_timeline)
    next_w_name     = next_weather["condition"]

    # Always use safe_best_compound so we never get None
    best_next       = safe_best_compound(next_w_name, current_compound)
    weather_change  = (best_next != current_compound) and compound_available(best_next)

    # Only trigger weather change pit if the new compound is actually better
    # AND we have inventory — prevents thrashing when all sets are gone
    if weather_change:
        current_mult = tyre_props[current_compound][WEATHER_FRICTION_KEY[next_w_name]]
        best_mult    = tyre_props[best_next][WEATHER_FRICTION_KEY[next_w_name]]
        # Only worth pitting if significantly better (>5% improvement)
        weather_change = (best_mult - current_mult) / current_mult > 0.05

    fuel_needed = estimate_fuel_per_lap(
        best_next if weather_change else current_compound, next_w_name)

    tyre_danger = tyre_life < TYRE_LIFE_DANGER
    fuel_danger = current_fuel < fuel_needed * FUEL_RESERVE_LAPS

    # Only pit for tyre change if we actually have a set available
    can_change_tyre = compound_available(best_next if weather_change else current_compound) or \
                      any_tyre_available()
    must_pit = (tyre_danger or fuel_danger or weather_change) and \
               lap_num < num_laps and can_change_tyre

    pit_entry = {"enter": must_pit}

    if must_pit:
        reasons = []
        if tyre_danger:    reasons.append(f"tyre={tyre_life:.3f}")
        if fuel_danger:    reasons.append(f"fuel={current_fuel:.2f}L")
        if weather_change: reasons.append(f"wx {w_name}->{next_w_name}")

        # Pick new compound: prefer weather-optimal, fallback through compounds
        if weather_change or tyre_danger:
            new_compound = best_next if compound_available(best_next) else None
            if new_compound is None:
                for alt in ["Hard", "Medium", "Intermediate", "Soft", "Wet"]:
                    if compound_available(alt):
                        new_compound = alt
                        break
            if new_compound is None:
                # No sets left at all — only refuel, keep current compound
                new_compound = current_compound
        else:
            new_compound = current_compound

        # Only get a new tyre ID if we're actually changing and have inventory
        if new_compound != current_compound and compound_available(new_compound):
            new_tyre_id      = get_next_tyre_id(new_compound)
            current_compound = new_compound
            current_tyre_id  = new_tyre_id
            tyre_life        = 1.0
            pit_entry["tyre_change_set_id"] = new_tyre_id
        elif tyre_danger and compound_available(current_compound):
            # Same compound, different set
            new_tyre_id     = get_next_tyre_id(current_compound)
            current_tyre_id = new_tyre_id
            tyre_life       = 1.0
            pit_entry["tyre_change_set_id"] = new_tyre_id

        refuel_l    = max(0.0, round(tank_capacity - current_fuel, 2))
        refuel_time = refuel_l / refuel_rate if refuel_l > 0 else 0.0
        elapsed_time += pit_base_time + pit_tyre_time + refuel_time
        current_fuel  = tank_capacity

        if refuel_l > 0:
            pit_entry["fuel_refuel_amount_l"] = refuel_l

        print(f"  Lap {lap_num:>2}: PIT [{', '.join(reasons)}] -> {current_compound} "
              f"(ID {current_tyre_id}) refuel={refuel_l:.1f}L t={elapsed_time:.1f}s")

    laps_out.append({
        "lap":      lap_num,
        "segments": lap_segments_out,
        "pit":      pit_entry
    })

# ── Write output ───────────────────────────────────────────────────────────────
output = {
    "initial_tyre_id": _initial_tyre_id,
    "laps": laps_out
}

with open("level4_output.txt", "w") as f:
    json.dump(output, f, indent=2)

import os
print(f"\n✓ level4_output.txt written to: {os.path.abspath('level4_output.txt')}")
print(f"  Total time : {elapsed_time:.2f}s")
print(f"  Fuel left  : {current_fuel:.2f}L")
print(f"  Tyre life  : {tyre_life:.3f}")
print(f"  Reference  : {race_data['race']['time_reference_s']}s")