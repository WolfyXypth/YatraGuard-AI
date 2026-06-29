import time
import requests


def run_user_simulation(target_url: str):
    """
    Runs the official YatraGuard-AI trekker timeline in the background.
    Receives the public ngrok URL dynamically so the code never needs updating.
    """
    print(f"\n[Simulation] Starting timeline — posting to {target_url}/risk\n")

    timeline_readings = [
        {
            "name": "08:00 AM — Safe at Checkpoint",
            "data": {
                "altitude_m": 3000,
                "previous_altitude_m": 2800,
                "hours_to_climb": 2.0,
                "heart_rate": 75,
                "spo2": 95.0,
            },
        },
        {
            "name": "12:00 PM — Pushing Hard & Tired",
            "data": {
                "altitude_m": 3800,
                "previous_altitude_m": 3000,
                "hours_to_climb": 4.0,
                "heart_rate": 105,
                "spo2": 88.0,
                "headache": True,
            },
        },
        {
            "name": "04:00 PM — Severe Hypoxia Hit",
            "data": {
                "altitude_m": 4500,
                "previous_altitude_m": 3800,
                "hours_to_climb": 4.0,
                "heart_rate": 120,
                "spo2": 78.0,
                "headache": True,
                "confusion": True,
            },
        },
    ]

    for stage in timeline_readings:
        print(f"─── {stage['name']} ───")
        try:
            response = requests.post(f"{target_url}/risk", json=stage["data"], timeout=10)
            if response.ok:
                result = response.json()
                print(f"  Risk Score : {result['risk_score']}/100")
                print(f"  Risk Level : {result['risk_level']}")
                print(f"  Conditions : {', '.join(result['conditions'])}")
                print(f"  Top Advice : {result['recommendations'][0]}")
            else:
                print(f"  ERROR {response.status_code}: {response.text}")
        except Exception as e:
            print(f"  Failed to reach /risk — {e}")
        print()
        time.sleep(5)

    print("[Simulation] Timeline complete.\n")