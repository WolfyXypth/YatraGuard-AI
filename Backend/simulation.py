import time
import requests

def run_user_simulation(target_url):
    """
    Runs the official YatraGuard-AI trekker timeline in the background.
    Takes target_url dynamically so it works over Ngrok.
    """
    print("\n[Simulation Core] Starting timeline sequence for a new trekker scan...")
    
    timeline_readings = [
        {
            "name": "08:00 AM - Safe at Checkpoint", 
            "data": {
                "altitude_m": 3000, 
                "previous_altitude_m": 2800, 
                "hours_to_climb": 2.0, 
                "heart_rate": 75, 
                "spo2": 95.0
            }
        },
        {
            "name": "12:00 PM - Pushing Hard & Tired", 
            "data": {
                "altitude_m": 3800, 
                "previous_altitude_m": 3000, 
                "hours_to_climb": 4.0, 
                "heart_rate": 105, 
                "spo2": 88.0, 
                "headache": True
            }
        },
        {
            "name": "04:00 PM - Severe Hypoxia Hit", 
            "data": {
                "altitude_m": 4500, 
                "previous_altitude_m": 3800, 
                "hours_to_climb": 4.0, 
                "heart_rate": 120, 
                "spo2": 78.0, 
                "headache": True, 
                "confusion": True
            }
        }
    ]

    for stage in timeline_readings:
        print(f"Sending Stage: {stage['name']}...")
        try:

            response = requests.post(f"{target_url}/risk", json=stage['data'])
            print(f"Server Response: Status {response.status_code} | Logged.")
        except Exception as e:
            print(f"Failed to hit /risk endpoint: {e}")
        
        time.sleep(5)
        
    print("[Simulation Core] Timeline sequence complete.\n")