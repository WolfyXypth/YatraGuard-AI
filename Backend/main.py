
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

class ReadingIn(BaseModel):

    altitude_m: float = Field(..., ge=0, le=8849, description="Current altitude in metres")
    previous_altitude_m: float = Field(..., ge=0, le=8849, description="Altitude at start of today's climb")
    hours_to_climb: float = Field(..., gt=0, le=24, description="Hours taken to climb from previous to current altitude")

    heart_rate: int = Field(..., ge=20, le=250, description="Resting heart rate (bpm)")
    spo2: float = Field(..., ge=50, le=100, description="Blood oxygen saturation (%)")
    respiratory_rate: Optional[float] = Field(None, ge=4, le=60, description="Breaths per minute")

    headache: bool = False
    dizziness: bool = False
    nausea: bool = False
    shortness_of_breath: bool = False
    confusion: bool = False 
    loss_of_balance: bool = False  

    @field_validator("spo2")
    @classmethod
    def spo2_max_100(cls, v):
        if v > 100:
            raise ValueError("SpO2 cannot exceed 100%")
        return v


class RiskOut(BaseModel):
    risk_score: int                  # 0–100
    risk_level: str                  # Low / Moderate / High / Very High / Critical
    ascent_rate_m_per_hour: float
    ascent_rate_m_per_day: float     # 24 h for easy comparison
    safe_rate: bool                  # True if within WMS guideline
    conditions: list[str]
    recommendations: list[str]
    score_breakdown: dict



def _ascent_points(gained_m: float, rate_m_per_hour: float, current_alt: float) -> int:

    rate_per_day = rate_m_per_hour * 8

    if current_alt < 2750:
        # 2750 m in one day is the low-risk ceiling
        if rate_per_day <= 1500:   # reasonable for low altitude
            return 0
        return 5

    if current_alt < 3000:
        if rate_per_day <= 800:
            return 5
        if rate_per_day <= 1200:
            return 12
        return 20

    # Above 3000 m: limit is 500 m/day
    if rate_per_day <= 500:
        return 5    # nominal altitude exposure even at safe rate
    if rate_per_day <= 700:
        return 15   # slightly fast
    if rate_per_day <= 1000:
        return 28   # notably fast — significant AMS risk
    if rate_per_day <= 1500:
        return 40   # dangerously fast
    return 55       # extreme rate — very high AMS/HAPE/HACE risk


def _spo2_points(spo2: float, altitude_m: float) -> int:
    """
    SpO2 is altitude-adjusted. Expected resting ranges:
      < 2500 m  → ≥ 94 %
      2500–3500 m → ≥ 90 %
      3500–5500 m → ≥ 85 %
      > 5500 m  → ≥ 80 %
    Source: ISMM consensus; Hacé Cuentas altitude calculator (updated June 2026)
    """
    if altitude_m < 2500:
        if spo2 >= 94: return 0
        if spo2 >= 90: return 8
        if spo2 >= 85: return 18
        return 30

    if altitude_m < 3500:
        if spo2 >= 90: return 0
        if spo2 >= 85: return 10
        if spo2 >= 80: return 22
        return 35

    if altitude_m < 5500:
        if spo2 >= 85: return 0
        if spo2 >= 80: return 12
        if spo2 >= 75: return 25
        return 38

    # > 5500 m extreme altitude
    if spo2 >= 80: return 0
    if spo2 >= 75: return 12
    return 30


def _hr_points(hr: int) -> int:
    """
    Resting tachycardia at altitude = sympathetic stress.
    Normal resting HR: 60–100 bpm (AHA).
    """
    if hr <= 100: return 0
    if hr <= 110: return 5
    if hr <= 120: return 10
    if hr <= 140: return 18
    return 25


def _rr_points(rr: Optional[float]) -> int:
    """Elevated respiratory rate at rest is an early HAPE warning."""
    if rr is None: return 0
    if rr <= 20: return 0
    if rr <= 24: return 5
    if rr <= 30: return 12
    return 20


def _symptom_points(r: ReadingIn) -> int:
    """
    Symptom weights based on 2018 Lake Louise Score severity tiers.
    Confusion / loss_of_balance are HACE criteria — carry extra weight here
    but also trigger immediate recommendations regardless of total score.
    """
    pts = 0
    if r.headache:             pts += 10
    if r.dizziness:            pts += 8
    if r.nausea:               pts += 8
    if r.shortness_of_breath:  pts += 20
    if r.confusion:            pts += 25
    if r.loss_of_balance:      pts += 25
    return pts


def _combination_penalty(r: ReadingIn, gained_m: float) -> tuple[int, list[str]]:
    """Extra penalties for dangerous co-occurring findings."""
    penalty = 0
    flags: list[str] = []

    # Fast climb + low SpO2: the body hasn't caught up
    if gained_m > 500 and r.spo2 < 88 and r.altitude_m >= 3000:
        penalty += 15
        flags.append("Rapid ascent with hypoxia — high AMS/HAPE risk")

    # HAPE pattern: dyspnoea + hypoxia at altitude
    if r.shortness_of_breath and r.spo2 < 90 and r.altitude_m >= 2500:
        penalty += 18
        flags.append("Possible HAPE: dyspnoea at rest with low SpO2")

    # HACE pattern: neurological signs at altitude (WMS 2024: descend immediately)
    if (r.confusion or r.loss_of_balance) and r.altitude_m >= 2500:
        penalty += 20
        flags.append("HACE suspected: neurological signs — immediate descent required")

    return penalty, flags


def score_to_level(score: int) -> str:
    if score <= 20: return "Low"
    if score <= 40: return "Moderate"
    if score <= 60: return "High"
    if score <= 80: return "Very High"
    return "Critical"


def recommend(level: str, r: ReadingIn, flags: list[str], rate_per_day: float, safe_rate: bool) -> list[str]:
    # HACE overrides everything. neurological signs = evacuate
    if r.confusion or r.loss_of_balance:
        return [
            "IMMEDIATE DESCENT — do not wait",
            "Administer dexamethasone 8 mg if available (WMS 2024)",
            "Supplement oxygen to reach SpO2 > 90 % if available",
            "Activate emergency evacuation",
            "Do not leave trekker alone",
        ]

    if level == "Low":
        recs = ["Conditions are safe — continue at current pace"]
        if not safe_rate:
            recs.append(f"Ascent rate ({rate_per_day:.0f} m/day equivalent) exceeds the WMS guideline of 500 m/day above 3000 m — consider slowing down")
        recs.append("Stay hydrated (3–4 L water/day)")
        return recs

    if level == "Moderate":
        return [
            "Stop ascending — rest at current altitude",
            f"Your ascent rate (~{rate_per_day:.0f} m/day) exceeds the safe limit of 500 m/day above 3000 m" if not safe_rate else "Monitor ascent rate carefully",
            "Drink fluids and avoid exertion for 24 hours",
            "Monitor SpO2 and heart rate every 30 minutes",
            "Descend if symptoms worsen",
        ]

    if level == "High":
        return [
            "Do NOT ascend further",
            "Rest at current altitude; descend if no improvement in 12–24 h",
            "Use supplemental oxygen if available",
            "Seek medical evaluation as soon as possible",
            "Monitor every 15 minutes",
        ]

    if level == "Very High":
        return [
            "Descend at least 500–1000 m immediately",
            "Supplemental oxygen to achieve SpO2 > 90 %",
            "Contact rescue services",
            "Do not wait — descend even at night if necessary",
        ]

    # Critical
    return [
        "MEDICAL EMERGENCY — evacuate immediately",
        "Descend as far and as fast as possible",
        "Supplemental oxygen at maximum flow rate",
        "Use Gamow bag if descent is impossible",
        "Activate helicopter rescue",
    ]


def calculate_risk(r: ReadingIn) -> RiskOut:
    gained_m = max(0.0, r.altitude_m - r.previous_altitude_m)
    rate_m_per_hour = gained_m / r.hours_to_climb
    rate_m_per_day = rate_m_per_hour * 8  # equivalent daily rate

    # WMS safe rate: ≤ 500 m/day above 3000 m
    safe_rate = (r.altitude_m < 3000) or (rate_m_per_day <= 500)

    # Score components
    a_pts  = _ascent_points(gained_m, rate_m_per_hour, r.altitude_m)
    s_pts  = _spo2_points(r.spo2, r.altitude_m)
    hr_pts = _hr_points(r.heart_rate)
    rr_pts = _rr_points(r.respiratory_rate)
    sym_pts = _symptom_points(r)
    combo_pts, flags = _combination_penalty(r, gained_m)

    raw = a_pts + s_pts + hr_pts + rr_pts + sym_pts + combo_pts
    score = min(raw, 100)
    level = score_to_level(score)

    conditions: list[str] = []
    if score >= 20 and r.headache:
        conditions.append("Acute Mountain Sickness (AMS) likely")
    if r.confusion or r.loss_of_balance:
        conditions.append("High-Altitude Cerebral Edema (HACE) suspected")
    if r.shortness_of_breath and r.spo2 < 90:
        conditions.append("High-Altitude Pulmonary Edema (HAPE) suspected")
    if not conditions:
        conditions.append("No acute altitude illness detected")

    return RiskOut(
        risk_score=score,
        risk_level=level,
        ascent_rate_m_per_hour=round(rate_m_per_hour, 1),
        ascent_rate_m_per_day=round(rate_m_per_day, 1),
        safe_rate=safe_rate,
        conditions=conditions,
        recommendations=recommend(level, r, flags, rate_m_per_day, safe_rate),
        score_breakdown={
            "ascent_rate_points": a_pts,
            "spo2_points": s_pts,
            "heart_rate_points": hr_pts,
            "respiratory_rate_points": rr_pts,
            "symptom_points": sym_pts,
            "combination_penalty": combo_pts,
            "raw_total": raw,
            "final_score": score,
            "emergency_flags": flags,
        },
    )


app = FastAPI(
    title="Sagarmatha Guard",
    description="Altitude risk assessment based on ascent rate and vitals (WMS 2024).",
    version="2.0.0",
)


@app.get("/")
def root():
    return {"status": "ok", "docs": "/docs"}


@app.post("/risk", response_model=RiskOut)
def assess_risk(reading: ReadingIn):
    """
    Submit a smartwatch reading and get an instant risk assessment.

    The primary risk driver is **ascent rate** (metres gained ÷ hours taken).
    Vitals (SpO2, heart rate, respiratory rate) and symptoms add further points.

    WMS 2024 safe rate: ≤ 500 m per day above 3000 m.
    """
    if reading.previous_altitude_m > reading.altitude_m:
        raise HTTPException(
            status_code=422,
            detail="previous_altitude_m cannot be higher than altitude_m for an ascent reading. "
                   "If descending, risk is not assessed."
        )
    return calculate_risk(reading)

from fastapi import FastAPI, BackgroundTasks 
from fastapi.responses import HTMLResponse
import simulation 
app = FastAPI()

@app.get("/scan-demo")
async def scan_demo(background_tasks: BackgroundTasks):
    """
    Triggered instantly on QR scan. Delivers the phone screen, 
    then runs the simulation loop in the background.
    """
    MY_CURRENT_URL = "https://backless-flatly-freebie.ngrok-free.dev" 
    background_tasks.add_task(simulation.run_user_simulation, MY_CURRENT_URL)
    

    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>YatraGuard-AI Demo</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background-color: #0f172a; color: #f8fafc; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; text-align: center; }
            .card { background: #1e293b; padding: 2.5rem 2rem; border-radius: 16px; border: 1px solid #334155; max-width: 85%; }
            .status-icon { font-size: 3.5rem; margin-bottom: 1rem; animation: pulse 2s infinite; }
            h1 { font-size: 1.6rem; color: #38bdf8; margin: 0 0 0.75rem 0; }
            p { color: #94a3b8; font-size: 0.95rem; line-height: 1.6; margin: 0 0 1.5rem 0; }
            .badge { background-color: #059669; color: white; padding: 0.6rem 1.2rem; border-radius: 9999px; font-weight: 600; font-size: 0.85rem; display: inline-block; }
            @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .6; } }
        </style>
    </head>
    <body>
        <div class="card">
            <div class="status-icon">🏔️</div>
            <h1>YatraGuard-AI Active</h1>
            <p>Your phone has triggered a personal vitals stream. Watch the master console terminal to see the AI evaluate your risk levels in real time!</p>
            <span class="badge">📡 Simulation Initiated</span>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)

if __name__ == "__main__":
    import uvicorn
    import os
    # Pull port from the cloud environment, default to 8000 if running locally
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)