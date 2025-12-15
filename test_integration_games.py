import requests
import json
import time

BASE_URL = "http://localhost:8000/api/games"

def test_integration():
    game_no = f"TEST_{int(time.time())}"
    print(f"Testing with game_no: {game_no}")

    # 1. POST PRE
    print("\n--- 1. Testing POST PRE ---")
    pre_payload = {
        "game_no": game_no,
        "latest_statistic": "2B/1E",
        "rate_big": 55.5,
        "rate_small": 44.5,
        "pre_raw": {"test": "pre"}
    }
    r = requests.post(f"{BASE_URL}/pre/", json=pre_payload)
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text}")
    assert r.status_code in [200, 201]
    data = r.json()
    assert data['has_pre'] == True
    assert float(data['rate_big']) == 55.5

    # 2. PATCH WINNER
    print("\n--- 2. Testing PATCH WINNER ---")
    winner_payload = {
        "winning_number": 18,
        "reward_numbers": [5, 4, 9],
        "status": 3,
        "is_reward": 2,
        "reward_type": "Big/Even",
        "winner_raw": {"test": "winner"}
    }
    r = requests.patch(f"{BASE_URL}/{game_no}/winner/", json=winner_payload)
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text}")
    assert r.status_code == 200
    data = r.json()
    assert data['has_winner'] == True
    assert data['winning_number'] == 18
    assert data['reward_numbers'] == [5, 4, 9]

    # 3. GET DETAILS
    print("\n--- 3. Testing GET DETAILS ---")
    r = requests.get(f"{BASE_URL}/{game_no}/")
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text}")
    assert r.status_code == 200
    data = r.json()
    assert data['game_no'] == game_no

    print("\nSUCCESS!")

if __name__ == "__main__":
    try:
        test_integration()
    except Exception as e:
        print(f"\nFAILED: {e}")
