import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from simulator.fleet_sim import VirtualRider
from scripts.run_chaos_scenarios import (
    run_strike_1_stale_gps,
    run_strike_2_concurrency_race,
    run_strike_3_competing_batch,
    run_strike_4_outbox_idempotency,
    run_strike_5_instance_failover_spec,
    run_strike_6_degraded_mode_health
)

def test_phase7_virtual_rider_mechanics():
    """Verifies fleet simulation logic, coordinate drift, and noisy packet generation."""
    # Clean rider
    rider = VirtualRider("rider_sim_001", mode="clean")
    p1 = rider.step()
    p2 = rider.step()
    assert p2["seq"] > p1["seq"], "Clean rider must have monotonically increasing seq"
    assert 12.93 <= p2["lat"] <= 13.00, "Latitude must stay within Bengaluru bounds"
    assert 77.56 <= p2["lon"] <= 77.67, "Longitude must stay within Bengaluru bounds"

    # Noisy rider
    noisy_rider = VirtualRider("rider_sim_noisy", mode="noisy")
    for _ in range(50):
        noisy_rider.step()
    assert noisy_rider.seq > 1

def test_phase7_all_six_chaos_strikes_pass():
    """Executes all 6 judge adversarial chaos strikes and asserts 100% verification."""
    assert run_strike_1_stale_gps() is True, "Strike 1: Stale GPS rejection failed"
    assert run_strike_2_concurrency_race() is True, "Strike 2: Concurrency hammer failed"
    assert run_strike_3_competing_batch() is True, "Strike 3: Competing batch assignment failed"
    assert run_strike_4_outbox_idempotency() is True, "Strike 4: Outbox ledger idempotency failed"
    assert run_strike_5_instance_failover_spec() is True, "Strike 5: Failover spec failed"
    assert run_strike_6_degraded_mode_health() is True, "Strike 6: Degraded mode verification failed"

def test_phase7_benchmark_scorecard_targets():
    """Verifies that BENCHMARK_SCORECARD.json exists and satisfies all hackathon requirements."""
    scorecard_path = Path("BENCHMARK_SCORECARD.json")
    assert scorecard_path.exists(), "BENCHMARK_SCORECARD.json must exist"

    with open(scorecard_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["total_scenarios"] == 1000, "Scorecard must verify 1,000 scenarios"
    m = data["metrics"]
    assert m["total_scenarios_tested"] == 1000, "Total scenarios tested must be 1,000"
    assert m["total_passed"] == 1000, "All 1,000 scenarios must pass (100%)"
    assert m["pass_rate_percentage"] == 100.0, "Pass rate must be 100%"

    assert m["double_assignments"] == 0, "Double assignments must be strictly 0"
    assert m["monotonic_violations"] == 0, "Monotonic sequence violations must be strictly 0"
    assert m["duplicate_notifications"] == 0, "Duplicate notifications must be strictly 0"
    assert m["nearest_rider_p95_ms"] < 50.0, "p95 assignment latency must be < 50ms"
    assert m["db_writes_per_sec"] < 50.0, "Database write downsampling must be < 50 writes/s"

def test_phase7_defence_documentation_complete():
    """Verifies the presence and completeness of all required design defence documentation."""
    spec_path = Path("SPEC.md")
    adr_path = Path("DECISION_RECORD.md")
    arch_path = Path("ARCHITECTURE.md")

    assert spec_path.exists(), "SPEC.md must exist"
    assert adr_path.exists(), "DECISION_RECORD.md must exist"
    assert arch_path.exists(), "ARCHITECTURE.md must exist"

    adr_text = adr_path.read_text(encoding="utf-8")
    assert "Judge Interview Defence" in adr_text, "ADR must contain Judge Interview Defence"
    assert "Zero Double Bookings" in adr_text
    assert "Transactional Outbox" in adr_text
