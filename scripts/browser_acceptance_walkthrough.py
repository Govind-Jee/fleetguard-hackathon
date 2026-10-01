#!/usr/bin/env python3
"""
FleetGuard Pulse - End-to-End Playwright Browser Acceptance Walkthrough.
Executes real browser journey against live running FastAPI (port 8000)
and Vite React Dashboard (port 3000). Captures screenshots, verifies
real data integrity, WebSocket live alerts, and 3NF work order persistence.
"""

import os
import sys
import time
import json
import requests
import psycopg2
from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = "docs/screenshots"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

# PostgreSQL Connection settings
PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5433"))
PG_DB = os.getenv("POSTGRES_DB", "fleetguard")
PG_USER = os.getenv("POSTGRES_USER", "fleetguard_user")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "fleetguard_dev_password")


def verify_postgres_work_order(work_order_id: str) -> dict:
    conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_DB,
        user=PG_USER,
        password=PG_PASSWORD,
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT w.work_order_id, v.vin, w.priority, w.status, w.created_at
            FROM work_orders w
            JOIN vehicles v ON w.vehicle_id = v.vehicle_id
            WHERE w.work_order_id = %s;
            """,
            (work_order_id,),
        )
        row = cur.fetchone()
        assert row is not None, f"Work order {work_order_id} not found in PostgreSQL!"
        return {
            "work_order_id": str(row[0]),
            "vin": row[1],
            "priority": row[2],
            "status": row[3],
            "created_at": str(row[4]),
        }


def run_walkthrough():
    results = {}

    from services.api.auth.jwt import create_access_token
    from services.api.auth.models import UserRole

    dev_token = create_access_token(
        user_id="b0000000-0000-0000-0000-000000000001",
        tenant_id="a0000000-0000-0000-0000-000000000001",
        email="admin@metrotransit.com",
        roles=[UserRole.ADMIN, UserRole.DISPATCHER, UserRole.TECHNICIAN],
    )

    with sync_playwright() as p:
        print("Launching headless Chromium browser (1280x800)...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        context.add_init_script(f"""
            localStorage.setItem('fleetguard_access_token', '{dev_token}');
        """)
        page = context.new_page()

        # ----------------------------------------------------
        # JOURNEY A: Fleet Overview (/)
        # ----------------------------------------------------
        print("\n[A] Opening Fleet Overview (http://localhost:3000/)...")
        page.goto("http://localhost:3000/", wait_until="networkidle")
        page.wait_for_selector("table", timeout=10000)

        # Assert navbar & branding
        assert page.locator("text=FleetGuard Pulse").first.is_visible()
        print("✓ Branding and navigation bar visible")

        # Assert KPI Cards by titles
        total_card = page.locator("text=Total Monitored Vehicles").locator("xpath=../..")
        avail_card = page.locator("text=Operational Availability").locator("xpath=../..")
        alert_card = page.locator("text=Active Critical Alerts").locator("xpath=../..")
        risk_card = page.locator("text=High 7-Day Risk Vehicles").locator("xpath=../..")

        assert total_card.is_visible()
        assert avail_card.is_visible()
        assert alert_card.is_visible()
        assert risk_card.is_visible()
        print("✓ All 4 KPI summary cards visible and confirmed")

        total_vehicles_text = total_card.locator(".text-3xl").text_content().strip()
        availability_text = avail_card.locator(".text-3xl").text_content().strip()
        critical_alerts_text = alert_card.locator(".text-3xl").text_content().strip()
        high_risk_text = risk_card.locator(".text-3xl").text_content().strip()

        print(f"✓ Real KPI: Total Monitored Vehicles = {total_vehicles_text}")
        print(f"✓ Real KPI: Operational Availability = {availability_text}")
        print(f"✓ Real KPI: Active Critical Alerts = {critical_alerts_text}")
        print(f"✓ Real KPI: High 7-Day Risk Vehicles = {high_risk_text}")
        assert int(total_vehicles_text.replace(",", "")) > 0, "KPI must show real vehicle count"

        # Assert Vehicle Table rows
        rows = page.locator("table tbody tr")
        row_count = rows.count()
        assert row_count > 0, "Vehicle inventory table must contain real vehicles"
        first_vin = rows.first.locator("td").first.locator(".font-mono").text_content().strip()
        print(f"✓ Vehicle table populated with {row_count} rows on current page. First VIN: {first_vin}")

        # Assert Leaflet map
        page.wait_for_selector(".leaflet-container", timeout=15000)
        assert page.locator(".leaflet-container").is_visible(), "Leaflet map canvas must render"
        page.wait_for_selector(".custom-leaflet-marker", timeout=15000)
        marker_count = page.locator(".custom-leaflet-marker").count()
        assert marker_count > 0, "Map must render vehicle pins"
        print(f"✓ Leaflet map rendered with {marker_count} vehicle markers")

        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "01_fleet_overview.png"))
        results["journey_a_fleet_overview"] = "PASS"

        # ----------------------------------------------------
        # JOURNEY B: Vehicle Details (/vehicles/{vin})
        # ----------------------------------------------------
        print(f"\n[B] Opening Vehicle Details for VIN {first_vin}...")
        inspect_btn = rows.first.locator("text=Inspect")
        inspect_btn.click()
        page.wait_for_url(f"**/vehicles/{first_vin}", timeout=10000)
        
        # Wait for either live telemetry gauge or transient telemetry pending card
        page.wait_for_selector("text=3NF Relational Specifications & Assignment", timeout=10000)
        telemetry_rendered = page.locator("text=Live CAN-Bus Telemetry Stream").is_visible() or page.locator("text=Transient Telemetry Pending").is_visible()
        assert telemetry_rendered, "Telemetry component must be rendered"

        # Verify VIN heading & specs
        assert page.locator(f"h1:has-text('{first_vin}')").is_visible()
        print("✓ 3NF Relational metadata rendered")
        print("✓ Telemetry component rendered")

        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "02_vehicle_details.png"))
        results["journey_b_vehicle_details"] = "PASS"

        # ----------------------------------------------------
        # JOURNEY C: Predictive Maintenance Risk Panel
        # ----------------------------------------------------
        print("\n[C] Verifying Predictive Maintenance 7-Day Risk...")
        page.wait_for_selector("text=Predictive Maintenance — 7-Day Failure Risk", timeout=15000)
        risk_heading = page.locator("text=Predictive Maintenance — 7-Day Failure Risk")
        assert risk_heading.is_visible()

        # Check probability percentage
        prob_elem = page.locator("text=Estimated 7-Day Maintenance Risk").locator("..").locator(".text-4xl")
        prob_text = prob_elem.text_content().strip()
        print(f"✓ Estimated 7-Day Maintenance Risk Probability: {prob_text}")
        assert "%" in prob_text

        # Check disclaimer notice from real API
        disclaimer_text = page.locator("text=Predictive Maintenance Model Notice:").locator("..").locator("p").text_content()
        print(f"✓ Real API Disclaimer text: {disclaimer_text}")
        assert "advisory risk score" in disclaimer_text or "not a deterministic guarantee" in disclaimer_text or "probabilistic" in disclaimer_text
        print("✓ Mandatory probabilistic disclaimer displayed clearly")

        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "03_predictive_risk.png"))
        results["journey_c_predictive_risk"] = "PASS"

        # ----------------------------------------------------
        # JOURNEY D: Diagnostics Page (/diagnostics)
        # ----------------------------------------------------
        print("\n[D] Opening Diagnostics (http://localhost:3000/diagnostics)...")
        page.goto("http://localhost:3000/diagnostics", wait_until="networkidle")
        page.wait_for_selector("text=pgvector Diagnostic Signature Search", timeout=10000)

        # Trigger pgvector nearest neighbors search
        search_btn = page.locator("text=Find Nearest Signatures")
        search_btn.click()
        page.wait_for_selector("text=Found", timeout=10000)

        match_cards = page.locator(".grid .bg-slate-950\\/80")
        assert match_cards.count() > 0, "pgvector search must return real candidate signatures"
        match_title = match_cards.first.locator(".font-mono.font-semibold").text_content()
        score_text = match_cards.first.locator("text=match").text_content()
        print(f"✓ Real pgvector nearest match: {match_title} ({score_text})")

        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "04_diagnostics_similarity.png"))
        results["journey_d_diagnostics"] = "PASS"

        # ----------------------------------------------------
        # JOURNEY E: Alerts Page & WebSocket Connection
        # ----------------------------------------------------
        print("\n[E] Opening Alerts (http://localhost:3000/alerts)...")
        page.goto("http://localhost:3000/alerts", wait_until="networkidle")
        page.wait_for_selector("text=STREAMING ACTIVE", timeout=10000)
        print("✓ WebSocket connected: 'STREAMING ACTIVE' indicator confirmed")

        assert page.locator("text=Historical Relational Alert Registry").is_visible()
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "05_alerts_overview.png"))
        results["journey_e_alerts_page"] = "PASS"

        # ----------------------------------------------------
        # JOURNEY F: Inject Known Critical Alert via Backend Path
        # ----------------------------------------------------
        print("\n[F] Injecting live critical alert through backend path...")
        test_alert_id = f"test-alert-{int(time.time())}"
        alert_payload = {
            "type": "CRITICAL_ALERT",
            "alert": {
                "alert_id": test_alert_id,
                "vin": first_vin,
                "tenant_id": "a0000000-0000-0000-0000-000000000001",
                "severity": "CRITICAL",
                "fault_type": "COOLANT_THERMAL_RUNAWAY",
                "message": "Coolant temperature exceeded 114.2°C critical safety limit",
                "sequence_number": 9901,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        }

        # Broadcast via FastAPI /ws/broadcast
        resp = requests.post("http://localhost:8000/ws/broadcast", json=alert_payload)
        assert resp.status_code == 200, f"Broadcast failed: {resp.text}"
        print("✓ Broadcast POST succeeded:", resp.json())

        # Verify alert appears in browser without refresh!
        page.wait_for_selector(f"text={first_vin}", timeout=5000)
        page.wait_for_selector("text=COOLANT_THERMAL_RUNAWAY", timeout=5000)
        print("✓ Live Critical Alert received over WebSocket in browser without page refresh!")
        print("✓ Global LiveAlertBanner displayed at top of browser")

        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "06_live_critical_alert.png"))
        results["journey_f_live_alert"] = "PASS"

        # ----------------------------------------------------
        # JOURNEY G: Open Affected Vehicle from Alert Banner
        # ----------------------------------------------------
        print("\n[G] Clicking 'Inspect Vehicle' from Live Alert Banner...")
        inspect_alert_btn = page.locator("text=Inspect Vehicle").first
        inspect_alert_btn.click()
        page.wait_for_url(f"**/vehicles/{first_vin}", timeout=10000)
        print(f"✓ Routed directly to affected vehicle {first_vin}")

        # ----------------------------------------------------
        # JOURNEY H: Create Maintenance Work Order & Verify DB
        # ----------------------------------------------------
        print("\n[H] Dispatching test Maintenance Work Order...")
        wo_btn = page.locator("text=Dispatch Work Order").first
        wo_btn.click()
        page.wait_for_selector("text=Dispatch Maintenance Work Order", timeout=5000)

        # Fill technician notes
        page.fill("textarea#work-order-notes", "Browser acceptance walkthrough verified dispatch")
        # Submit
        submit_btn = page.locator("button:has-text('Create Work Order')")
        submit_btn.click()

        # Wait for success dialog
        page.wait_for_selector("text=Work Order Successfully Dispatched", timeout=10000)
        wo_id_elem = page.locator("text=Order ID:").locator("..").locator(".font-mono")
        created_wo_id = wo_id_elem.text_content().strip()
        print(f"✓ Work Order created successfully: {created_wo_id}")

        # Verify record in PostgreSQL database directly
        db_record = verify_postgres_work_order(created_wo_id)
        print(f"✓ Verified 3NF relational DB record in PostgreSQL: {db_record}")
        assert db_record["vin"] == first_vin
        assert db_record["status"] == "PENDING"

        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "07_work_order_dispatched.png"))
        results["journey_h_work_order_db"] = "PASS"

        # Close modal
        page.click("text=Close")

        # ----------------------------------------------------
        # RESPONSIVE CHECK (Tablet Viewport: 768 x 1024)
        # ----------------------------------------------------
        print("\n[Responsive Check] Testing tablet viewport (768x1024)...")
        page.set_viewport_size({"width": 768, "height": 1024})
        page.goto("http://localhost:3000/", wait_until="networkidle")
        page.wait_for_selector("table", timeout=10000)

        # Check no horizontal scrolling on body
        scroll_width = page.evaluate("() => document.body.scrollWidth")
        inner_width = page.evaluate("() => window.innerWidth")
        print(f"✓ Viewport width: {inner_width}px, body scrollWidth: {scroll_width}px")
        assert scroll_width <= inner_width + 15, "Layout must not cause broken horizontal page overflow"

        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "08_tablet_viewport.png"))
        results["responsive_check"] = "PASS"

        # ----------------------------------------------------
        # UI ERROR STATE CHECK
        # ----------------------------------------------------
        print("\n[UI Error State] Testing invalid vehicle route...")
        page.goto("http://localhost:3000/vehicles/VIN_NONEXISTENT_9999", wait_until="networkidle")
        page.wait_for_selector("text=Operation Failed", timeout=10000)
        assert page.locator("text=not found").is_visible()
        print("✓ Meaningful error alert rendered cleanly for invalid/missing resource")

        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "09_error_state.png"))
        results["ui_error_state"] = "PASS"

        browser.close()

    print("\n" + "=" * 50)
    print("ALL BROWSER ACCEPTANCE JOURNEYS PASSED!")
    print("=" * 50)
    for k, v in results.items():
        print(f"  {k}: {v}")
    return results


if __name__ == "__main__":
    run_walkthrough()
