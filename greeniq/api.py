"""HTTP API + the one-port web app. Routes contain no business logic: they read ComputedFacts.

    GET  /api/health
    GET  /api/portfolio                       portfolio KPIs, band distribution, triage
    GET  /api/properties                      list / search / filter (from the portfolio cache)
    GET  /api/properties/{id}                 full ComputedFacts + template explanation
    GET  /api/properties/{id}/next-best-action
    POST /api/properties/{id}/scenarios       what-if → analyse_home reruns → new facts

"Insufficient information" is a STATUS inside the facts, never an HTTP error.
Errors share one shape: {"error": {"code": ..., "message": ...}}.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from .contract import MeasureId
from .engines.nba import DEFAULT_OBJECTIVE, OBJECTIVES
from .facts import Scenario
from .service import GreenIQService, UnknownProperty
from .trust.narrator import explain_home, explain_package

WEB_DIR = Path(__file__).parent / "web"


class ScenarioRequest(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    measures: list[MeasureId] | None = None  # None = the recommended package
    order: str = "recommended"
    objective: str = DEFAULT_OBJECTIVE
    declined_measures: list[MeasureId] = Field(default_factory=list)
    completed_measures: list[MeasureId] = Field(default_factory=list)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def create_app(service: GreenIQService | None = None) -> FastAPI:
    state: dict = {"svc": service}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if state["svc"] is None:
            state["svc"] = GreenIQService()
        yield

    app = FastAPI(title="GreenIQ", version="1.0", lifespan=lifespan)

    def svc() -> GreenIQService:
        return state["svc"]

    @app.exception_handler(UnknownProperty)
    async def _unknown(_: Request, exc: UnknownProperty):
        return _error(404, "unknown_property", f"No property with id {exc.args[0]!r}.")

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, exc: RequestValidationError):
        return _error(422, "invalid_request", "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        return _error(exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(ValueError)
    async def _value(_: Request, exc: ValueError):
        return _error(422, "invalid_request", str(exc))

    @app.exception_handler(Exception)
    async def _crash(_: Request, exc: Exception):
        return _error(500, "internal_error", f"{type(exc).__name__}: the engine could not complete this request.")

    @app.get("/api/health")
    def health():
        s = svc()
        return {"status": "ok", "homes": len(s.rows()), "engine_key": s.engine_key, "versions": s.versions,
                "providers": s.providers, "llm": "off (template narrator)"}

    @app.get("/api/evidence")
    def evidence():
        """Methodology receipts: versions, providers, factors, costs, and the generated evaluation metrics."""
        import json

        from .data import ROOT
        from .engines.catalogue import catalogue, emission_factors

        def read(path):
            p = ROOT / path
            return json.loads(p.read_text()) if p.exists() else None

        s = svc()
        cat = catalogue()
        return {
            "engine_key": s.engine_key, "versions": s.versions, "providers": s.providers,
            "emission_factors": emission_factors(),
            "measures": {k: {"name": m["name"], "stage": m["stage"], "cost": m["cost"], "cost_source": m.get("cost_source"),
                             "lifetime_years": m.get("lifetime_years")} for k, m in cat["measures"].items()},
            "metrics": read("reports/metrics.json"), "model_card": read("models/model_card.json"),
            "data_card": "data/DATA_CARD.md", "evaluation_report": "reports/EVALUATION.md",
            "scoring_method": "docs/SCORING_METHOD.md", "methodology": "docs/METHODOLOGY.md",
        }

    @app.get("/api/portfolio")
    def portfolio():
        return svc().portfolio()

    @app.get("/api/properties")
    def properties(q: str | None = None, band: str | None = None, region: str | None = None,
                   property_type: str | None = None, disposition: str | None = None, poor_only: bool = False,
                   sort: str = "property_id", limit: int = 50, offset: int = 0):
        return svc().search(q, band, region, property_type, disposition, poor_only, sort, min(max(limit, 1), 500),
                            max(offset, 0))

    @app.get("/api/properties/{property_id}")
    def property_report(property_id: str):
        f = svc().facts(property_id)
        return {"facts": f.model_dump(mode="json"), "explanation": explain_home(f).model_dump()}

    @app.get("/api/properties/{property_id}/next-best-action")
    def next_best_action(property_id: str, objective: str = DEFAULT_OBJECTIVE):
        if objective not in OBJECTIVES:
            raise ValueError(f"unknown objective {objective!r}; choose one of {sorted(OBJECTIVES)}")
        f = svc().facts(property_id) if objective == DEFAULT_OBJECTIVE else \
            svc().scenario(property_id, None, {"objective": objective})
        return f.next_best_action.model_dump(mode="json")

    @app.post("/api/properties/{property_id}/scenarios")
    def scenario(property_id: str, req: ScenarioRequest):
        if req.order not in ("recommended", "as_given"):
            raise ValueError("order must be 'recommended' or 'as_given'")
        if req.objective not in OBJECTIVES:
            raise ValueError(f"unknown objective {req.objective!r}; choose one of {sorted(OBJECTIVES)}")
        sc = Scenario(name=req.name, measures=req.measures, order=req.order)
        constraints = {"objective": req.objective, "declined_measures": req.declined_measures,
                       "completed_measures": req.completed_measures}
        f = svc().scenario(property_id, sc, constraints)
        return {"facts": f.model_dump(mode="json"), "explanation": explain_package(f).model_dump()}

    @app.middleware("http")
    async def _revalidate_static(request: Request, call_next):
        resp = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            resp.headers["Cache-Control"] = "no-cache"  # always revalidate: the UI must match the engine version
        return resp

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")

    return app


app = create_app()
