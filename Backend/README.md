# Sagarmatha Guard v2

Simple altitude risk API. **Two files: `main.py` and `test_main.py`.**

## Run

```bash
pip install -r requirements.txt
uvicorn main:app --reload
# → http://localhost:8000/docs
```

## The one endpoint

### `POST /risk`

```json
{
  "altitude_m": 4500,
  "previous_altitude_m": 3000,
  "hours_to_climb": 4,
  "heart_rate": 115,
  "spo2": 83,
  "respiratory_rate": 26,
  "headache": true,
  "shortness_of_breath": true
}
```

**Response:**
```json
{
  "risk_score": 78,
  "risk_level": "Very High",
  "ascent_rate_m_per_hour": 375.0,
  "ascent_rate_m_per_day": 3000.0,
  "safe_rate": false,
  "conditions": ["Acute Mountain Sickness (AMS) likely", "High-Altitude Pulmonary Edema (HAPE) suspected"],
  "recommendations": [
    "Descend at least 500–1000 m immediately",
    "Supplemental oxygen to achieve SpO2 > 90 %",
    "Contact rescue services",
    "Do not wait — descend even at night if necessary"
  ],
  "score_breakdown": {
    "ascent_rate_points": 40,
    "spo2_points": 25,
    "heart_rate_points": 10,
    "respiratory_rate_points": 12,
    "symptom_points": 30,
    "combination_penalty": 18,
    "raw_total": 135,
    "final_score": 78,
    "emergency_flags": ["Rapid ascent with hypoxia — high AMS/HAPE risk", "Possible HAPE: dyspnoea at rest with low SpO2"]
  }
}
```

## How scoring works

| Component | Basis |
|---|---|
| **Ascent rate** (primary) | WMS 2024 / CDC: ≤ 500 m/day above 3000 m is safe. Rate = (altitude gained) ÷ hours |
| **SpO2** | Altitude-adjusted norms (≥90% at 2500–3500 m; ≥85% at 3500–5500 m) |
| **Heart rate** | Resting tachycardia = poor acclimatisation |
| **Respiratory rate** | Elevated RR at rest = early HAPE warning |
| **Symptoms** | Lake Louise Score weights (confusion/ataxia = HACE → immediate descent) |

## Risk levels

| Score | Level | Action |
|---|---|---|
| 0–20 | Low | Continue |
| 21–40 | Moderate | Rest, don't ascend |
| 41–60 | High | Halt, seek medical help |
| 61–80 | Very High | Descend now |
| 81–100 | Critical | Evacuate |

## Tests
```bash
pytest test_main.py -v   # 11 tests
```
