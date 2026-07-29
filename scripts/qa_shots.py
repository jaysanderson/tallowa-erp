"""Screenshot the demo at 1920x1080 for QA and the deck pipeline.

Start the app first, then:  ../../.venv/bin/python scripts/qa_shots.py
Writes shots/*.png. Live AI calls are made where a panel needs an answer, so
allow a few minutes.
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "shots"
BASE = "http://127.0.0.1:8061"


def main():
    SHOTS.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 1920, "height": 1080})

        pg.goto(BASE + "/login")
        pg.wait_for_selector("#f")
        pg.screenshot(path=SHOTS / "00-login.png")
        pg.fill("#email", "plant@tallowacomponents.com.au")
        pg.fill("#pw", "demo1234")
        pg.click("button[type=submit]")
        pg.wait_for_url(BASE + "/")

        # dashboard - briefing autoruns; full_page so the below-the-fold
        # "Open quality holds" panel (the fixed blocked-units story) is
        # captured too, not just the KPI row.
        pg.wait_for_selector(".kpi .v", timeout=20000)
        try:
            pg.wait_for_selector("#briefing .ai-answer", timeout=90000)
        except Exception:
            pass
        pg.screenshot(path=SHOTS / "01-dashboard.png", full_page=True)

        # copilot cited answer
        pg.goto(BASE + "/copilot")
        pg.wait_for_selector("#q")
        pg.fill("#q", "What torque does the EPB-40 output fastener take, and "
                      "what happens if a reading is out of window?")
        pg.click("#go")
        pg.wait_for_selector("#out .ai-answer", timeout=90000)
        pg.screenshot(path=SHOTS / "02-copilot.png")

        # ops assistant - live steps (fixed hero: blocked units + both
        # exposed shipments now resolve correctly - see BUILD-STATE.md)
        pg.goto(BASE + "/ops-assistant")
        pg.wait_for_selector("#q")
        pg.fill("#q", "Which customer shipments are exposed to fastener lot "
                      "WF-2261 and what is blocked on site?")
        pg.click("#go")
        pg.wait_for_selector("#ans .ai-answer", timeout=120000)
        pg.wait_for_selector("#ans .grounding:has-text('Completed')",
                             timeout=15000)
        # full_page: the answer (both shipments + both blocked quantities)
        # runs well past one 1080px viewport - capture all of it, deck-builder
        # crops the section it needs.
        pg.screenshot(path=SHOTS / "03-ops-assistant.png", full_page=True)

        # traceability - hero lot + narrative
        pg.goto(BASE + "/traceability")
        pg.wait_for_selector("#result table", timeout=30000)
        pg.screenshot(path=SHOTS / "04-traceability.png")
        pg.click("#traceai .btn")
        pg.wait_for_selector("#traceai .ai-answer", timeout=120000)
        # full_page: the 8D containment narrative runs past one viewport and
        # is where "300 units blocked on-site" is spelled out explicitly.
        pg.screenshot(path=SHOTS / "05-traceability-narrative.png",
                      full_page=True)

        # playbooks
        pg.goto(BASE + "/playbooks")
        # options in a closed <select> are never "visible" to Playwright
        pg.wait_for_selector("#part option", state="attached")
        pg.click("#go")
        pg.wait_for_selector("#out .ai-answer", timeout=120000)
        pg.screenshot(path=SHOTS / "06-playbook.png")

        # insights - run two cards
        pg.goto(BASE + "/insights")
        pg.wait_for_selector("#c1 .btn")
        pg.click("#c1 .btn.orange")
        pg.click("#c2 .btn.orange")
        pg.wait_for_selector("#c1 .ai-answer", timeout=120000)
        pg.wait_for_selector("#c2 .ai-answer", timeout=120000)
        pg.screenshot(path=SHOTS / "07-insights.png")

        # production run detail (held run)
        pg.goto(BASE + "/production/RUN-1101")
        pg.wait_for_selector("#mats table", timeout=30000)
        pg.screenshot(path=SHOTS / "08-run-detail.png")

        # quality
        pg.goto(BASE + "/quality")
        pg.wait_for_selector("#defs table", timeout=30000)
        pg.screenshot(path=SHOTS / "09-quality.png")

        # parts
        pg.goto(BASE + "/parts")
        pg.wait_for_selector("#rows table", timeout=30000)
        pg.screenshot(path=SHOTS / "10-parts.png")

        # api docs
        pg.goto(BASE + "/docs")
        pg.wait_for_selector(".swagger-ui", timeout=30000)
        pg.wait_for_timeout(1500)
        pg.screenshot(path=SHOTS / "11-api-docs.png")

        b.close()
    print("shots written to", SHOTS)


if __name__ == "__main__":
    main()
