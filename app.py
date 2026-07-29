"""Tallowa Components - Plant Operations (demo).

API-first ERP for a fictional Australian tier-1 automotive components maker,
with grounded AI features woven through. The web app talks only to /api/*;
Swagger for the whole surface is published at /docs.

Run locally:  ../../.venv/bin/python -m uvicorn app:app --port 8061
"""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import ai
import erp
import mcp
from database import DB_PATH

ROOT = Path(__file__).resolve().parent

if not DB_PATH.exists():
    import seed_db
    seed_db.main()

app = FastAPI(
    title="Tallowa Components - Plant API",
    version="2.4.0",
    description=(
        "The operations API for the Bellbrook plant. The whole platform is "
        "built on this API - the web app only ever talks to these endpoints. "
        "Authenticate via POST /api/auth/login, then send the token as "
        "`Authorization: Bearer <token>`. All data is synthetic demonstration "
        "content; every company, person, part and lot is fictional."),
)

app.include_router(erp.router)
app.include_router(ai.router)
mcp.mount(app)   # hosted MCP surface - AFTER the routers so the catalogue is complete


@app.middleware("http")
async def noindex(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


@app.get("/robots.txt")
def robots():
    return PlainTextResponse("User-agent: *\nDisallow: /\n")


SHELL = (ROOT / "static" / "shell.html").read_text()

# route -> (page file, title). Detail routes reuse their list page's file suffixed -detail.
PAGES = {
    "/": ("dashboard", "Dashboard"),
    "/customers": ("customers", "Customers"),
    "/production": ("production", "Production runs"),
    "/sales-orders": ("sales-orders", "Sales orders"),
    "/parts": ("parts", "Parts & BOM"),
    "/lots": ("lots", "Lots"),
    "/traceability": ("traceability", "Traceability"),
    "/suppliers": ("suppliers", "Suppliers"),
    "/purchase-orders": ("purchase-orders", "Purchase orders"),
    "/shipments": ("shipments", "Shipments"),
    "/invoices": ("invoices", "Invoices"),
    "/machines": ("machines", "Machines & tooling"),
    "/operators": ("operators", "People & certifications"),
    "/quality": ("quality", "Quality"),
    "/ap-invoices": ("ap-invoices", "AP Invoices"),
    "/ctp": ("ctp", "Capable-to-Promise"),
    "/plant": ("plant", "Plant & lines"),
    "/reports": ("reports", "Reports"),
    "/recurring": ("recurring", "Release schedules"),
    "/audit": ("audit", "Audit trail"),
    "/settings": ("settings", "Settings"),
    "/integrations": ("integrations", "Integrations"),
    "/copilot": ("copilot", "Knowledge Copilot"),
    "/ops-assistant": ("ops-assistant", "Ops Assistant"),
    "/playbooks": ("playbooks", "Build Playbooks"),
    "/insights": ("insights", "AI Insights"),
}

DETAIL_PAGES = {
    "/customers/{cid}": "customer-detail",
    "/production/{run_no}": "production-detail",
    "/sales-orders/{so_no}": "sales-order-detail",
    "/parts/{part_no}": "part-detail",
    "/suppliers/{code}": "supplier-detail",
    "/purchase-orders/{po_no}": "purchase-order-detail",
}


def render(page: str, title: str) -> HTMLResponse:
    body = (ROOT / "static" / "pages" / f"{page}.html").read_text()
    return HTMLResponse(SHELL.replace("{{TITLE}}", title)
                        .replace("{{PAGE}}", page)
                        .replace("{{BODY}}", body))


@app.get("/login", response_class=HTMLResponse)
def login_page():
    return HTMLResponse((ROOT / "static" / "login.html").read_text())


for route, (fname, title) in PAGES.items():
    def make(fname=fname, title=title):
        def handler():
            return render(fname, title)
        return handler
    app.get(route, response_class=HTMLResponse, include_in_schema=False)(make())

for route, fname in DETAIL_PAGES.items():
    # FastAPI needs the path parameter declared by name in the handler signature
    param = route.split("{")[1].split("}")[0]
    ns = {"render": render}
    exec(f"def handler({param}: str):\n    return render({fname!r}, 'Detail')", ns)
    app.get(route, response_class=HTMLResponse,
            include_in_schema=False)(ns["handler"])


@app.exception_handler(404)
async def not_found(request: Request, exc):
    if request.url.path.startswith("/api/"):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return HTMLResponse(SHELL.replace("{{TITLE}}", "Not found")
                        .replace("{{PAGE}}", "notfound")
                        .replace("{{BODY}}",
                                 (ROOT / "static" / "pages" / "notfound.html")
                                 .read_text()), status_code=404)


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
