import json
import math
import sys
sys.stdout.reconfigure(encoding="utf-8")
# ── Load race data ─────────────────────────────────────────────────────────────
race_data = json.load(open("level-3/level3.json"))

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

# ── Tyre set lookup ────────────────────────────────────────────────────────────
compound_to_id = {entry["compound"]: entry["ids"][0] for entry in available_sets}

# ── Weather state machine ──────────────────────────────────────────────────────
# Build a flat timeline of (start_time, end_time, condition_dict)
# Conditions cycle if race outlasts all durations.

def build_weather_timeline(total_race_estimate_s):
    """Returns list of (start_s, end_s, condition) covering total_race_estimate_s."""
    timeline = []
    t = 0.0
    cycle = weather_conditions
    while t < total_race_estimate_s + 10000:
        for cond in cycle:
            timeline.append((t, t + cond["duration_s"], cond))
            t += cond["duration_s"]
    return timeline

def get_weather_at(elapsed_s, timeline):
    for (start, end, cond) in timeline:
        if start <= elapsed_s < end:
            return cond
    return timeline[-1][2]  # fallback

def get_friction_multiplier(compound, weather_condition_name):
    key = f"{weather_condition_name}_friction_multiplier"
    return tyre_props[compound][key]

# ── Tyre strategy: pick best compound per weather condition ────────────────────
# Priority: highest friction multiplier for the current weather wins.
# We evaluate all available compounds and pick the best for each condition type.

def best_compound_for_weather(weather_name):
    best, best_mult = None, -1
    for entry in available_sets:
        compound = entry["compound"]
        mult = get_friction_multiplier(compound, weather_name)
        if mult > best_mult:
            best_mult = mult
            best = compound
    return best

# Pre-compute best compounds
print("Best tyre per weather condition:")
for cond in weather_conditions:
    wname = cond["condition"]
    best  = best_compound_for_weather(wname)
    print(f"  {wname:12s} → {best} (friction mult: {get_friction_multiplier(best, wname):.3f})")

# ── Core physics helpers ───────────────────────────────────────────────────────
def max_corner_speed(compound, weather_name, radius):
    friction = get_friction_multiplier(compound, weather_name)
    return math.sqrt(friction * 9.8 * radius) + crawl_constant

def braking_dist(v_initial, v_final, weather_decel_mult):
    effective_brake = brake_decel * weather_decel_mult
    if v_initial <= v_final:
        return 0.0
    return (v_initial**2 - v_final**2) / (2 * effective_brake)

def segment_time(seg, target_speed, entry_speed, exit_speed, weather):
    """Estimate wall-clock seconds to traverse a segment."""
    length = seg["length_m"]
    decel_mult  = weather["deceleration_multiplier"]
    accel_mult  = weather["acceleration_multiplier"]

    if seg["type"] == "corner":
        return length / target_speed

    # Straight: accel → cruise → brake
    effective_accel = accel * accel_mult
    effective_brake = brake_decel * decel_mult

    # Acceleration phase
    accel_dist = max(0.0, (target_speed**2 - entry_speed**2) / (2 * effective_accel))
    brake_dist  = max(0.0, (target_speed**2 - exit_speed**2)  / (2 * effective_brake))
    accel_dist  = min(accel_dist, max(0.0, length - brake_dist))
    cruise_dist = max(0.0, length - accel_dist - brake_dist)

    t = 0.0
    if accel_dist > 0:
        t_accel = (target_speed - entry_speed) / effective_accel
        t += t_accel
    if cruise_dist > 0:
        t += cruise_dist / target_speed
    if brake_dist > 0:
        t_brake = (target_speed - exit_speed) / effective_brake
        t += t_brake
    return max(t, length / target_speed)  # safety floor

def pit_stop_time(refuel_l, changing_tyres):
    refuel_t = refuel_l / refuel_rate if refuel_l > 0 else 0.0
    tyre_t   = pit_tyre_time if changing_tyres else 0.0
    return pit_base_time + refuel_t + tyre_t

def fuel_used_phase(v_i, v_f, dist):
    avg = (v_i + v_f) / 2
    return (K_BASE + K_DRAG * avg**2) * dist

# ── Full race simulation ───────────────────────────────────────────────────────
# We simulate lap-by-lap, tracking time, fuel, and weather to decide:
#   1. Which tyre to run
#   2. Exact corner speeds & braking distances
#   3. When to pit (tyre change and/or refuel)

ESTIMATED_RACE_TIME = 35000  # generous upper bound in seconds
weather_timeline = build_weather_timeline(ESTIMATED_RACE_TIME)

elapsed_time = 0.0
current_fuel = initial_fuel
current_compound = None   # decided lap by lap
current_tyre_id  = None

laps_out = []

# Track previous tyre for pit decisions
prev_compound = None

print(f"\nSimulating {num_laps} laps...")

for lap_num in range(1, num_laps + 1):

    # ── Decide tyre for this lap ───────────────────────────────────────────────
    # Look at the weather at the START of this lap to pick our tyre.
    lap_start_weather = get_weather_at(elapsed_time, weather_timeline)
    best_compound_now = best_compound_for_weather(lap_start_weather["condition"])

    if current_compound is None:
        current_compound = best_compound_now
        current_tyre_id  = compound_to_id[current_compound]

    lap_segments_out = []
    lap_fuel_used    = 0.0

    # ── Simulate each segment ──────────────────────────────────────────────────
    for i, seg in enumerate(track_segments):
        weather = get_weather_at(elapsed_time, weather_timeline)
        w_name  = weather["condition"]

        if seg["type"] == "corner":
            speed = max_corner_speed(current_compound, w_name, seg["radius_m"])
            t     = segment_time(seg, speed, speed, speed, weather)
            elapsed_time += t
            lap_fuel_used += fuel_used_phase(speed, speed, seg["length_m"])
            lap_segments_out.append({"id": seg["id"], "type": "corner"})

        else:  # straight
            sid      = seg["id"]
            length   = seg["length_m"]
            decel_m  = weather["deceleration_multiplier"]

            # Entry speed: from previous segment
            prev_seg = seg_by_id.get(((sid - 2) % max_segment_id) + 1)
            if prev_seg and prev_seg["type"] == "corner":
                entry_speed = max_corner_speed(current_compound, w_name, prev_seg["radius_m"])
            else:
                entry_speed = min(max_speed, pit_exit_speed if lap_num > 1 else 0.0)

            # Exit speed: determined by the next segment
            next_seg = seg_by_id.get((sid % max_segment_id) + 1)
            if next_seg and next_seg["type"] == "corner":
                exit_speed = max_corner_speed(current_compound, w_name, next_seg["radius_m"])
            else:
                exit_speed = max_speed

            # Braking distance
            b_dist = braking_dist(max_speed, exit_speed, decel_m)
            b_dist = min(b_dist, length)  # can't brake longer than the straight

            t = segment_time(seg, max_speed, entry_speed, exit_speed, weather)
            elapsed_time += t

            # Fuel for this straight (3 phases)
            eff_accel = accel * weather["acceleration_multiplier"]
            accel_d   = max(0.0, (max_speed**2 - entry_speed**2) / (2 * eff_accel))
            accel_d   = min(accel_d, max(0.0, length - b_dist))
            cruise_d  = max(0.0, length - accel_d - b_dist)
            lap_fuel_used += fuel_used_phase(entry_speed, max_speed, accel_d)
            lap_fuel_used += fuel_used_phase(max_speed, max_speed, cruise_d)
            lap_fuel_used += fuel_used_phase(max_speed, exit_speed, b_dist)

            lap_segments_out.append({
                "id":                        sid,
                "type":                      "straight",
                "target_m/s":                round(max_speed, 4),
                "brake_start_m_before_next": round(b_dist, 4)
            })

    current_fuel -= lap_fuel_used

    # ── Pit stop decision ──────────────────────────────────────────────────────
    next_lap_weather     = get_weather_at(elapsed_time, weather_timeline)
    best_compound_next   = best_compound_for_weather(next_lap_weather["condition"])
    need_tyre_change     = (best_compound_next != current_compound) and (lap_num < num_laps)
    need_refuel          = (current_fuel < lap_fuel_used) and (lap_num < num_laps)
    entering_pit         = need_tyre_change or need_refuel

    pit_entry = {"enter": entering_pit}

    if entering_pit:
        refuel_l = 0.0
        if need_refuel:
            refuel_l = round(min(tank_capacity - current_fuel, tank_capacity), 2)

        new_tyre_id = None
        if need_tyre_change:
            new_tyre_id      = compound_to_id[best_compound_next]
            current_compound = best_compound_next
            current_tyre_id  = new_tyre_id

        if refuel_l > 0:
            pit_entry["fuel_refuel_amount_l"] = refuel_l
            current_fuel += refuel_l
        if new_tyre_id is not None:
            pit_entry["tyre_change_set_id"] = new_tyre_id

        # Add pit stop time to elapsed clock
        elapsed_time += pit_stop_time(refuel_l, need_tyre_change)

        print(f"  Lap {lap_num:>2}: PIT | tyre={'→'+best_compound_next if need_tyre_change else 'keep':<16} "
              f"refuel={refuel_l:.1f}L | weather={next_lap_weather['condition']} | t={elapsed_time:.1f}s")

    laps_out.append({
        "lap":      lap_num,
        "segments": lap_segments_out,
        "pit":      pit_entry
    })

# ── Output ─────────────────────────────────────────────────────────────────────
output = {
    "initial_tyre_id": compound_to_id[laps_out[0]["segments"][0]["type"] and
                       best_compound_for_weather(
                           get_weather_at(0.0, weather_timeline)["condition"])],
    "laps": laps_out
}

# Fix initial_tyre_id cleanly
initial_weather_name = get_weather_at(0.0, weather_timeline)["condition"]
initial_compound     = best_compound_for_weather(initial_weather_name)
output["initial_tyre_id"] = compound_to_id[initial_compound]

with open("level3_output.txt", "w") as f:
    json.dump(output, f, indent=2)

print(f"\n✓ level3_output.txt written.")
print(f"  Total simulated time : {elapsed_time:.2f}s")
print(f"  Remaining fuel       : {current_fuel:.2f}L")
print(f"  Reference time       : {race_data['race']['time_reference_s']}s")