import json
import math
import os

def solve_level3(input_file="level.json", output_file="submission.json"):
    """
    LEVEL 3: Weather management
    - Track weather changes over time
    - Choose optimal tyres for current weather
    - Plan pit stops for tyre changes + refueling
    - Adjust speeds based on weather conditions
    """
    
    # Load JSON data
    with open(input_file, 'r') as f:
        data = json.load(f)
    
    car = data['car']
    track = data['track']
    tyres = data['tyres']
    available_sets = data['available_sets']
    race = data['race']
    weather_data = data.get('weather', {})
    
    # Constants
    GRAVITY = 9.8
    K_BASE = 0.0005
    K_DRAG = 1.5e-9
    
    crawl_speed = car['crawl_constant_m/s']
    max_speed = car['max_speed_m/s']
    brake_rate = car['brake_m/se2']
    accel_rate = car['accel_m/se2']
    fuel_capacity = car['fuel_tank_capacity_l']
    initial_fuel = car['initial_fuel_l']
    
    segments = track['segments']
    n_segs = len(segments)
    total_laps = race['laps']
    
    # === WEATHER TRACKING ===
    weather_conditions = weather_data.get('conditions', [])
    
    def get_weather_at_time(race_time):
        """Get weather condition at specific race time"""
        if not weather_conditions:
            return {"condition": "dry", "acceleration_multiplier": 1.0, 
                    "deceleration_multiplier": 1.0}
        
        total_cycle = sum(w['duration_s'] for w in weather_conditions)
        if total_cycle == 0:
            return weather_conditions[0]
        
        time_in_cycle = race_time % total_cycle
        
        for w in weather_conditions:
            if time_in_cycle < w['duration_s']:
                return w
            time_in_cycle -= w['duration_s']
        
        return weather_conditions[0]
    
    def get_tyre_for_weather(weather_condition):
        """Select best tyre compound for current weather"""
        condition = weather_condition.get('condition', 'dry')
        
        # Map weather to best tyre
        if condition == 'heavy_rain':
            return 'Wet'
        elif condition == 'light_rain':
            return 'Intermediate'
        elif condition == 'cold':
            return 'Medium'  # Better longevity in cold
        else:  # dry
            return 'Soft'
    
    def get_friction_multiplier(compound, weather_condition):
        """Get friction multiplier for tyre + weather combo"""
        condition = weather_condition.get('condition', 'dry')
        prop = tyres['properties'][compound]
        
        multiplier_key = f"{condition}_friction_multiplier"
        return prop.get(multiplier_key, 1.0)
    
    # === INITIAL SETUP ===
    starting_weather = get_weather_at_time(0)
    initial_compound = get_tyre_for_weather(starting_weather)
    
    # Find tyre set
    initial_set = next((s for s in available_sets if s['compound'] == initial_compound), 
                       available_sets[0])
    initial_tyre_id = initial_set['ids'][0]
    
    # === BUILD SUBMISSION ===
    submission = {
        "initial_tyre_id": initial_tyre_id,
        "laps": []
    }
    
    current_fuel = initial_fuel
    current_tyre_compound = initial_compound
    current_tyre_id = initial_tyre_id
    race_time = 0.0
    
    # Track when we last changed tyres
    last_tyre_change_lap = 0
    
    for lap_num in range(1, total_laps + 1):
        lap_data = {
            "lap": lap_num,
            "segments": [],
            "pit": {"enter": False}
        }
        
        # Get weather at start of lap
        lap_weather = get_weather_at_time(race_time)
        
        # Check if we need to change tyres for weather
        optimal_compound = get_tyre_for_weather(lap_weather)
        need_tyre_change = (optimal_compound != current_tyre_compound and 
                           lap_num > last_tyre_change_lap)
        
        # Estimate fuel for this lap
        fuel_estimate = 0
        for seg in segments:
            if seg['type'] == 'straight':
                fuel_estimate += (K_BASE + K_DRAG * max_speed**2) * seg['length_m']
        
        need_refuel = current_fuel < fuel_estimate * 1.5  # Safety margin
        
        # Decide on pit stop
        do_pit = need_tyre_change or need_refuel
        
        if do_pit and lap_num < total_laps:
            # Calculate refuel amount
            refuel_amount = min(
                fuel_capacity - current_fuel,
                fuel_capacity * 0.95
            )
            
            # Get new tyre set if changing
            if need_tyre_change:
                new_set = next((s for s in available_sets 
                               if s['compound'] == optimal_compound), available_sets[0])
                new_tyre_id = new_set['ids'][0]
                current_tyre_compound = optimal_compound
                current_tyre_id = new_tyre_id
                last_tyre_change_lap = lap_num
                
                print(f"🌦️  Lap {lap_num}: Changing to {optimal_compound} tyres "
                      f"(Weather: {lap_weather['condition']})")
            else:
                new_tyre_id = None
            
            lap_data['pit'] = {
                "enter": True,
                "tyre_change_set_id": new_tyre_id,
                "fuel_refuel_amount_l": round(refuel_amount, 2) if need_refuel else 0
            }
            
            current_fuel += refuel_amount
            
            # Add pit stop time to race time
            pit_time = race['base_pit_stop_time_s']
            if new_tyre_id:
                pit_time += race['pit_tyre_swap_time_s']
            if need_refuel:
                pit_time += refuel_amount / race['pit_refuel_rate_l/s']
            
            race_time += pit_time
        
        # Calculate current tyre friction
        weather_mult = get_friction_multiplier(current_tyre_compound, lap_weather)
        base_fric = {
            'Soft': 1.8, 'Medium': 1.8, 'Hard': 1.7,
            'Intermediate': 1.6, 'Wet': 1.2
        }[current_tyre_compound]
        
        tyre_friction = base_fric * weather_mult
        
        # Adjust speed based on weather and fuel
        weather_cond = lap_weather.get('condition', 'dry')
        speed_mult = 1.0
        
        if weather_cond == 'heavy_rain':
            speed_mult = 0.75
        elif weather_cond == 'light_rain':
            speed_mult = 0.85
        elif weather_cond == 'cold':
            speed_mult = 0.95
        
        fuel_ratio = current_fuel / fuel_capacity
        if fuel_ratio < 0.3:
            speed_mult *= 0.9
        
        for i, seg in enumerate(segments):
            seg_data = {"id": seg['id'], "type": seg['type']}
            
            if seg['type'] == 'straight':
                next_seg = segments[(i + 1) % n_segs]
                
                target_speed = max_speed * speed_mult
                
                if next_seg['type'] == 'corner':
                    max_corner_speed = math.sqrt(
                        tyre_friction * GRAVITY * next_seg['radius_m']
                    ) + crawl_speed
                    exit_speed = min(max_corner_speed, target_speed)
                else:
                    exit_speed = target_speed
                
                # Calculate braking distance
                # Apply weather multiplier to braking
                brake_mult = lap_weather.get('deceleration_multiplier', 1.0)
                effective_brake = brake_rate * brake_mult
                
                if target_speed > exit_speed:
                    brake_dist = (target_speed**2 - exit_speed**2) / (2 * effective_brake)
                    brake_dist = max(0, min(brake_dist, seg['length_m']))
                else:
                    brake_dist = 0
                
                seg_data["target_m/s"] = round(target_speed, 2)
                seg_data["brake_start_m_before_next"] = round(brake_dist, 2)
                
                # Track fuel
                avg_speed = (target_speed + exit_speed) / 2
                fuel_used = (K_BASE + K_DRAG * avg_speed**2) * seg['length_m']
                current_fuel -= fuel_used
                
                # Estimate time for this segment
                seg_time = seg['length_m'] / max(avg_speed, crawl_speed)
                race_time += seg_time
            else:
                # Corner - estimate time
                corner_speed = math.sqrt(tyre_friction * GRAVITY * seg['radius_m']) + crawl_speed
                race_time += seg['length_m'] / max(corner_speed, crawl_speed)
            
            lap_data['segments'].append(seg_data)
        
        submission['laps'].append(lap_data)
    
    # Save output
    with open(output_file, 'w') as f:
        json.dump(submission, f, indent=2)
    
    print(f"✅ Level 3 complete!")
    print(f"   Final tyre compound: {current_tyre_compound}")
    print(f"   Fuel remaining: {current_fuel:.2f}L")
    print(f"   Estimated race time: {race_time:.2f}s")
    print(f"   Saved to {output_file}")
    
    return submission

if __name__ == "__main__":
    if not os.path.exists("level.json"):
        print("❌ level.json not found!")
    else:
        solve_level3()