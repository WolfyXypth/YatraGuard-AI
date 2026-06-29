from __future__ import annotations

import os
from typing import Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

import simulation


# ── Models ────────────────────────────────────────────────────────────────────

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
    risk_score: int
    risk_level: str
    ascent_rate_m_per_hour: float
    ascent_rate_m_per_day: float
    safe_rate: bool
    conditions: list[str]
    recommendations: list[str]
    score_breakdown: dict


# ── Scoring helpers ────────────────────────────────────────────────────────────

def _ascent_points(gained_m: float, rate_m_per_hour: float, current_alt: float) -> int:
    rate_per_day = rate_m_per_hour * 8
    if current_alt < 2750:
        return 0 if rate_per_day <= 1500 else 5
    if current_alt < 3000:
        if rate_per_day <= 800:  return 5
        if rate_per_day <= 1200: return 12
        return 20
    if rate_per_day <= 500:  return 5
    if rate_per_day <= 700:  return 15
    if rate_per_day <= 1000: return 28
    if rate_per_day <= 1500: return 40
    return 55


def _spo2_points(spo2: float, altitude_m: float) -> int:
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
    if spo2 >= 80: return 0
    if spo2 >= 75: return 12
    return 30


def _hr_points(hr: int) -> int:
    if hr <= 100: return 0
    if hr <= 110: return 5
    if hr <= 120: return 10
    if hr <= 140: return 18
    return 25


def _rr_points(rr: Optional[float]) -> int:
    if rr is None: return 0
    if rr <= 20: return 0
    if rr <= 24: return 5
    if rr <= 30: return 12
    return 20


def _symptom_points(r: ReadingIn) -> int:
    pts = 0
    if r.headache:             pts += 10
    if r.dizziness:            pts += 8
    if r.nausea:               pts += 8
    if r.shortness_of_breath:  pts += 20
    if r.confusion:            pts += 25
    if r.loss_of_balance:      pts += 25
    return pts


def _combination_penalty(r: ReadingIn, gained_m: float) -> tuple[int, list[str]]:
    penalty = 0
    flags: list[str] = []
    if gained_m > 500 and r.spo2 < 88 and r.altitude_m >= 3000:
        penalty += 15
        flags.append("Rapid ascent with hypoxia — high AMS/HAPE risk")
    if r.shortness_of_breath and r.spo2 < 90 and r.altitude_m >= 2500:
        penalty += 18
        flags.append("Possible HAPE: dyspnoea at rest with low SpO2")
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
    rate_m_per_day = rate_m_per_hour * 8
    safe_rate = (r.altitude_m < 3000) or (rate_m_per_day <= 500)

    a_pts   = _ascent_points(gained_m, rate_m_per_hour, r.altitude_m)
    s_pts   = _spo2_points(r.spo2, r.altitude_m)
    hr_pts  = _hr_points(r.heart_rate)
    rr_pts  = _rr_points(r.respiratory_rate)
    sym_pts = _symptom_points(r)
    combo_pts, flags = _combination_penalty(r, gained_m)

    raw   = a_pts + s_pts + hr_pts + rr_pts + sym_pts + combo_pts
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


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="YatraGuard-AI / Sagarmatha Guard",
    description="Altitude risk assessment based on ascent rate and vitals (WMS 2024).",
    version="2.0.0",
)

# Serve all HTML pages from the "frontend" folder.
# Put home.html, map.html, vitals.html, about.html inside a folder called "frontend"
# that sits next to this main.py file.
app.mount("/app", StaticFiles(directory="../frontend", html=True), name="frontend")


@app.get("/", include_in_schema=False)
def root():
    # Redirect bare root to the home page
    return RedirectResponse(url="/app/home.html")


@app.post("/risk", response_model=RiskOut)
def assess_risk(reading: ReadingIn):
    """
    Submit a smartwatch reading and get an instant risk assessment.
    WMS 2024 safe rate: ≤ 500 m per day above 3000 m.
    """
    if reading.previous_altitude_m > reading.altitude_m:
        raise HTTPException(
            status_code=422,
            detail="previous_altitude_m cannot be higher than altitude_m for an ascent reading."
        )
    return calculate_risk(reading)


@app.get("/scan-demo", include_in_schema=False)
async def scan_demo(request: Request, background_tasks: BackgroundTasks):
    """
    QR scan entry point. Immediately redirects to home.html,
    then fires the simulation in the background so the terminal shows live output.
    """
    public_url = os.environ.get(
        "NGROK_URL",
        str(request.base_url).rstrip("/")
    )
    print(f"[scan-demo] Scan received — simulation will post to {public_url}/risk")
    background_tasks.add_task(simulation.run_user_simulation, public_url)

    # Send the user straight to the real frontend home page
    return RedirectResponse(url="/app/home.html", status_code=302)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
