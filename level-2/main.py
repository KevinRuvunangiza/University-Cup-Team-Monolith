import json
import math

# ── Load race data ─────────────────────────────────────────────────────────────
race_data = json.load(open("level-2/level2.json"))

track_segments   = race_data["track"]["segments"]
crawl_constant   = race_data["car"]["crawl_constant_m/s"]
max_speed        = race_data["car"]["max_speed_m/s"]
brake_decel      = race_data["car"]["brake_m/se2"]
accel            = race_data["car"]["accel_m/se2"]
num_laps         = race_data["race"]["laps"]
tank_capacity    = race_data["car"]["fuel_tank_capacity_l"]
initial_fuel     = race_data["car"]["initial_fuel_l"]
refuel_rate      = race_data["race"]["pit_refuel_rate_l/s"]
fuel_soft_cap    = race_data["race"]["fuel_soft_cap_limit_l"]
pit_base_time    = race_data["race"]["base_pit_stop_time_s"]
pit_tyre_time    = race_data["race"]["pit_tyre_swap_time_s"]

# Fuel consumption constants (from problem statement)
K_BASE = 0.0005
K_DRAG = 0.0000000015

# Level 2 — dry only, Soft gives best friction, no tyre degradation
CHOSEN_COMPOUND  = "Soft"
INITIAL_TYRE_ID  = 1

dry_friction_multiplier = race_data["tyres"]["properties"][CHOSEN_COMPOUND]["dry_friction_multiplier"]

# ── Pass 1: Max safe corner speeds ─────────────────────────────────────────────
corner_speeds = {}
for seg in track_segments:
    if seg["type"] == "corner":
        max_safe_speed = math.sqrt(dry_friction_multiplier * 9.8 * seg["radius_m"]) + crawl_constant
        corner_speeds[seg["id"]] = max_safe_speed

seg_by_id      = {seg["id"]: seg for seg in track_segments}
max_segment_id = max(seg_by_id.keys())

# ── Pass 2: Straight actions (target speed + braking distance) ─────────────────
straight_actions = {}
for seg in track_segments:
    if seg["type"] == "straight":
        sid     = seg["id"]
        next_id = (sid % max_segment_id) + 1
        next_seg = seg_by_id.get(next_id)

        if next_seg and next_seg["type"] == "corner":
            final_speed      = corner_speeds[next_seg["id"]]
            braking_distance = (max_speed**2 - final_speed**2) / (2 * brake_decel)
        else:
            braking_distance = 0.0
            final_speed      = max_speed

        straight_actions[sid] = {
            "target_speed":  max_speed,
            "brake_start_m": braking_distance,
            "exit_speed":    final_speed,        # speed entering the next segment
            "length_m":      seg["length_m"]
        }

# ── Fuel calculation helpers ───────────────────────────────────────────────────
def fuel_for_phase(v_initial, v_final, distance):
    """Fuel used over a distance with a linearly changing speed (accel or brake phase)."""
    avg_speed = (v_initial + v_final) / 2
    return (K_BASE + K_DRAG * avg_speed**2) * distance

def fuel_for_segment(seg):
    """Total fuel used traversing one segment at max attack."""
    if seg["type"] == "corner":
        spd = corner_speeds[seg["id"]]
        return fuel_for_phase(spd, spd, seg["length_m"])

    # Straight: accel phase → cruise phase → brake phase
    sid    = seg["id"]
    action = straight_actions[sid]
    target = action["target_speed"]
    v_exit = action["exit_speed"]
    length = action["length_m"]
    brake  = action["brake_start_m"]

    # Estimate entry speed: previous segment exit speed
    prev_id  = ((sid - 2) % max_segment_id) + 1
    prev_seg = seg_by_id.get(prev_id)
    if prev_seg and prev_seg["type"] == "corner":
        v_entry = corner_speeds[prev_id]
    else:
        v_entry = max_speed   # pit exit or another straight

    # Acceleration phase distance
    accel_dist = max(0.0, (target**2 - v_entry**2) / (2 * accel))
    accel_dist = min(accel_dist, length - brake)

    # Cruise distance
    cruise_dist = max(0.0, length - brake - accel_dist)

    fuel  = fuel_for_phase(v_entry, target, accel_dist)
    fuel += fuel_for_phase(target, target, cruise_dist)
    fuel += fuel_for_phase(target, v_exit, brake)
    return fuel

# ── Calculate fuel used per lap ────────────────────────────────────────────────
fuel_per_lap = sum(fuel_for_segment(seg) for seg in track_segments)
print(f"Estimated fuel per lap: {fuel_per_lap:.4f} L")
print(f"Total fuel for {num_laps} laps: {fuel_per_lap * num_laps:.4f} L")
print(f"Tank capacity: {tank_capacity} L  |  Soft cap: {fuel_soft_cap} L")

# ── Pit stop strategy: refuel only when we'd run dry next lap ─────────────────
# We want to stay under the soft cap total while never running out mid-race.
# Strategy: refuel to full whenever fuel would drop below 1 lap's worth.

def plan_pit_stops():
    """
    Returns a dict: lap_number -> litres_to_refuel (0 means no pit).
    Never changes tyres in L2 (no degradation).
    """
    pits      = {}
    fuel      = initial_fuel
    total_refuelled = 0.0

    for lap in range(1, num_laps + 1):
        fuel -= fuel_per_lap

        # If after this lap we won't have enough for the next lap, refuel
        if lap < num_laps and fuel < fuel_per_lap:
            refuel_amount = min(tank_capacity - fuel, tank_capacity)
            # Don't exceed soft cap across total usage
            refuel_amount = round(refuel_amount, 2)
            pits[lap] = refuel_amount
            total_refuelled += refuel_amount
            fuel += refuel_amount

    print(f"\nPlanned pit stops: {len(pits)}")
    for lap, amt in pits.items():
        print(f"  End of lap {lap}: refuel {amt:.2f} L")
    print(f"Total fuel used (incl. refuels): {fuel_per_lap * num_laps:.4f} L")
    return pits

pit_schedule = plan_pit_stops()

# ── Build output segment list for one lap ─────────────────────────────────────
def build_lap_segments():
    out = []
    for seg in track_segments:
        if seg["type"] == "straight":
            action = straight_actions[seg["id"]]
            out.append({
                "id":                        seg["id"],
                "type":                      "straight",
                "target_m/s":                round(action["target_speed"], 4),
                "brake_start_m_before_next": round(action["brake_start_m"], 4)
            })
        else:
            out.append({
                "id":   seg["id"],
                "type": "corner"
            })
    return out

# ── Assemble full race output ──────────────────────────────────────────────────
laps_out = []
for lap_num in range(1, num_laps + 1):
    refuel_amt = pit_schedule.get(lap_num, 0)
    entering_pit = refuel_amt > 0

    pit_entry = {"enter": entering_pit}
    if entering_pit:
        pit_entry["fuel_refuel_amount_l"] = refuel_amt
        # No tyre change needed in L2

    laps_out.append({
        "lap":      lap_num,
        "segments": build_lap_segments(),
        "pit":      pit_entry
    })

output = {
    "initial_tyre_id": INITIAL_TYRE_ID,
    "laps": laps_out
}

# ── Write submission file ──────────────────────────────────────────────────────
with open("level2_output.txt", "w") as f:
    json.dump(output, f, indent=2)

print("\n✓ level2_output.txt written successfully.")
print(f"  Laps: {num_laps}  |  Tyre: {CHOSEN_COMPOUND} (ID {INITIAL_TYRE_ID})")