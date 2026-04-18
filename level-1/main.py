import json
import math
import sys
sys.stdout.reconfigure(encoding="utf-8")

# ── Load race data ─────────────────────────────────────────────────────────────
race_data = json.load(open("level1.json"))

track_segments = race_data["track"]["segments"]
crawl_constant  = race_data["car"]["crawl_constant_m/s"]
max_speed       = race_data["car"]["max_speed_m/s"]
brake_decel     = race_data["car"]["brake_m/se2"]
num_laps        = race_data["race"]["laps"]

# Level 1 is dry only — use Soft tyres (best friction, no degradation in L1)
CHOSEN_TYRE_COMPOUND = "Soft"
INITIAL_TYRE_ID      = 1          # ID 1 = Soft in available_sets

dry_friction_multiplier = race_data["tyres"]["properties"][CHOSEN_TYRE_COMPOUND]["dry_friction_multiplier"]

# ── Pass 1: Max safe speed for every corner ────────────────────────────────────
corner_speeds = {}
for seg in track_segments:
    if seg["type"] == "corner":
        max_safe_speed = math.sqrt(dry_friction_multiplier * 9.8 * seg["radius_m"]) + crawl_constant
        corner_speeds[seg["id"]] = max_safe_speed

# ── Pass 2: Braking distance for every straight ────────────────────────────────
seg_by_id      = {seg["id"]: seg for seg in track_segments}
max_segment_id = max(seg_by_id.keys())

straight_actions = {}   # straight_id -> {"target": float, "brake": float}

for seg in track_segments:
    if seg["type"] == "straight":
        sid = seg["id"]

        # Next segment (wrap around at end of track)
        next_id  = (sid % max_segment_id) + 1
        next_seg = seg_by_id.get(next_id)

        if next_seg and next_seg["type"] == "corner":
            final_speed      = corner_speeds[next_seg["id"]]
            braking_distance = (max_speed**2 - final_speed**2) / (2 * brake_decel)
        else:
            # Straight followed by straight — no braking needed
            braking_distance = 0.0

        straight_actions[sid] = {
            "target_speed":    max_speed,
            "brake_start_m":   braking_distance
        }

# ── Build the required JSON output structure ───────────────────────────────────
def build_lap_segments():
    segments_out = []
    for seg in track_segments:
        if seg["type"] == "straight":
            action = straight_actions[seg["id"]]
            segments_out.append({
                "id":                         seg["id"],
                "type":                       "straight",
                "target_m/s":                 round(action["target_speed"], 4),
                "brake_start_m_before_next":  round(action["brake_start_m"], 4)
            })
        else:  # corner
            segments_out.append({
                "id":   seg["id"],
                "type": "corner"
            })
    return segments_out

laps_out = []
for lap_num in range(1, num_laps + 1):
    laps_out.append({
        "lap":      lap_num,
        "segments": build_lap_segments(),
        "pit": {
            "enter": False
        }
    })

output = {
    "initial_tyre_id": INITIAL_TYRE_ID,
    "laps": laps_out
}

# ── Write to submission file ───────────────────────────────────────────────────
with open("level1_output.txt", "w") as f:
    json.dump(output, f, indent=2)

print("✓ level1_output.txt written successfully.")
print(f"  Laps: {num_laps}  |  Segments per lap: {len(track_segments)}  |  Tyre: {CHOSEN_TYRE_COMPOUND} (ID {INITIAL_TYRE_ID})")