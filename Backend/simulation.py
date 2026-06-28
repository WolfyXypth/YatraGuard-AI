import time
import requests

def run_user_simulation(ngrok_url):
    """This runs your timeline steps sequentially for a user"""
    print("Starting simulation sequence...")
    
    # Step 1: Base camp
    requests.post(f"{ngrok_url}/risk", json={"heart_rate": 78, "spo2": 96, "altitude": 3440})
    time.sleep(5)
    
    # Step 2: Ascent
    requests.post(f"{ngrok_url}/risk", json={"heart_rate": 105, "spo2": 88, "altitude": 4200})
    time.sleep(5)
    
    # Step 3: Critical
    requests.post(f"{ngrok_url}/risk", json={"heart_rate": 122, "spo2": 79, "altitude": 4900})
    print("✅ Simulation sequence complete.")