import json
import math

race_data = json.load(open("level1.json"))
track_segments = race_data["track"]["segments"]
crawl_constant = race_data["car"]["crawl_constant_m/s"]
soft_tyres = race_data["tyres"]["properties"]["Soft"]
dry_friction_multiplier = soft_tyres["dry_friction_multiplier"]

print(track_segments)
print("Soft Tyres: " + str(soft_tyres))
print("Crawl Constant: " + str(crawl_constant))
print("Dry Friction Multiplier: " + str(dry_friction_multiplier))

for segment in track_segments:
    print(segment)
    if segment["type"] == "straight":
        print("Straight Segment: " + str(segment["length"]))
    elif segment["type"] == "corner":
        print("Corner Segment: " + str(segment["angle"]))