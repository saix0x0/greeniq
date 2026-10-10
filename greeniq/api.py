"""HTTP API + the one-port web app. Routes contain no business logic: they read ComputedFacts.

    GET  /api/health
    GET  /api/portfolio                       portfolio KPIs, band distribution, triage
    GET  /api/properties                      list / search / filter (from the portfolio cache)
    GET  /api/properties/{id}                 full ComputedFacts + template explanation
    GET  /api/properties/{id}/next-best-action
    GET  /api/properties/{id}/lab             Decision Lab: all feasible packages, plans, interactions, sensitivity
    POST /api/properties/{id}/scenarios       what-if → analyse_home reruns → new facts
    POST /api/properties/{id}/ask             free-text what-if → scenario → rerun → gated explanation
    GET  /api/properties/{id}/gate-demo       the grounding gate passing honest text and blocking corrupted text

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
from .trust.assistant import interpret
from .trust.gate import check as gate_check
from .trust.llm import llm_status
from .trust.llm import provider as llm_provider
from .trust.llm import style as llm_style
from .trust.narrator import explain, explain_package

WEB_DIR = Path(__file__).parent / "web"


class ScenarioRequest(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    measures: list[MeasureId] | None = None  # None = the recommended package
    order: str = "recommended"
    objective: str = DEFAULT_OBJECTIVE
    declined_measures: list[MeasureId] = Field(default_factory=list)
    completed_measures: list[MeasureId] = Field(default_factory=list)


class AskRequest(BaseModel):
    question: str = Field(max_length=300)
    objective: str = DEFAULT_OBJECTIVE


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
                "providers": s.providers, "llm": llm_status()[1]}

    @app.get("/api/evidence")
    def evidence():
        """Methodology receipts: versions, providers, factors, costs, and the generated evaluation metrics."""
        import json

        from .config import score_mappings as SM
        from .data import ROOT
        from .engines.catalogue import assumptions, catalogue, emission_factors

        def read(path):
            p = ROOT / path
            return json.loads(p.read_text()) if p.exists() else None

        s = svc()
        cat = catalogue()
        return {
            "engine_key": s.engine_key, "versions": s.versions, "providers": s.providers,
            "emission_factors": emission_factors(),
            "measures": {k: {"name": m["name"], "stage": m["stage"], "cost": m["cost"], "cost_source": m.get("cost_source"),
                             "lifetime_years": m.get("lifetime_years"), "applicability": m.get("applicability"),
                             "ps2_illustrative_impact": m.get("ps2_illustrative_impact"),
                             "evidence_note": m.get("evidence_note")} for k, m in cat["measures"].items()},
            "stages": cat["stages"], "price_basis": cat.get("price_basis"), "impact_note": cat.get("impact_note"),
            "score": {"weights": SM.WEIGHTS, "labels": SM.LABELS, "bands": SM.BANDS, "version": SM.MAPPING_VERSION,
                      "issue_threshold": SM.ISSUE_SUBSCORE_THRESHOLD,
                      "mappings": {"intensity_kwh_m2": SM.INTENSITY_KNOTS, "loft_mm": SM.LOFT_KNOTS,
                                   "walls": [[f"{t} {'insulated' if i else 'uninsulated'}", v] for (t, i), v in SM.WALL_SCORES.items()],
                                   "insulation_element_weights": SM.INSULATION_ELEMENT_WEIGHTS,
                                   "heating": SM.HEATING_LADDER, "boiler_age_penalty": SM.BOILER_AGE_PENALTY_KNOTS,
                                   "glazing": SM.GLAZING_LADDER, "solar_kwp": SM.PV_KNOTS, "controls": SM.CONTROLS_LADDER,
                                   "epc_band_midpoint": SM.EPC_BAND_MIDPOINT}},
            "assumptions": assumptions(),
            "real_data": read("reports/real_data.json"),
            "calibration": {"name": s.ctx.calibration_name, "rates": s.ctx.calibration, "sources": s.ctx.calibration_source},
            "metrics": read("reports/metrics.json"), "model_card": read("models/model_card.json"),
            "data_card": "data/DATA_CARD.md", "evaluation_report": "reports/EVALUATION.md",
            "scoring_method": "docs/SCORING_METHOD.md", "methodology": "docs/METHODOLOGY.md",
        }

    @app.get("/api/portfolio")
    def portfolio():
        return svc().portfolio()

    @app.get("/api/portfolio/groups")
    def portfolio_groups(by: str = "region"):
        return svc().groups(by)

    @app.get("/api/properties")
    def properties(q: str | None = None, band: str | None = None, region: str | None = None,
                   property_type: str | None = None, disposition: str | None = None, poor_only: bool = False,
                   sort: str = "property_id", limit: int = 50, offset: int = 0, ids: str | None = None,
                   group_by: str | None = None, group: str | None = None, tier: str | None = None):
        return svc().search(q, band, region, property_type, disposition, poor_only, sort, min(max(limit, 1), 500),
                            max(offset, 0), ids, group_by, group, tier)

    @app.get("/api/properties/{property_id}")
    def property_report(property_id: str):
        f = svc().facts(property_id)
        return {"facts": f.model_dump(mode="json"), "explanation": explain(f, "home", use_model=False).model_dump()}

    explained: dict[tuple, dict] = {}

    @app.get("/api/properties/{property_id}/explain")
    def explain_endpoint(property_id: str, scope: str = "home", objective: str = DEFAULT_OBJECTIVE):
        """The language-model explanation of the score (scope=home) or the recommendations (scope=package).
        Reads the computed facts only; every sentence passes the grounding gate or the template is shown.
        Cached per (facts, scope, provider) so a demo never pays twice for the same explanation."""
        if scope not in ("home", "package"):
            raise ValueError("scope must be 'home' or 'package'")
        if objective not in OBJECTIVES:
            raise ValueError(f"unknown objective {objective!r}; choose one of {sorted(OBJECTIVES)}")
        f = svc().facts(property_id) if objective == DEFAULT_OBJECTIVE else \
            svc().scenario(property_id, None, {"objective": objective})
        prov = llm_provider()
        key = (f.facts_id, scope, prov[0], llm_style())
        if key not in explained:
            ex = explain(f, scope)
            out = {"explanation": ex.model_dump(), "provider": {"name": prov[0], "detail": prov[1]}}
            if ex.mode != "llm" and prov[0] != "off" and "timed out" in (ex.note or ""):
                return out  # do not cache transient failures
            explained[key] = out
        return explained[key]

    @app.get("/api/properties/{property_id}/standing")
    def standing(property_id: str):
        return svc().standing(property_id)

    @app.get("/api/properties/{property_id}/next-best-action")
    def next_best_action(property_id: str, objective: str = DEFAULT_OBJECTIVE):
        if objective not in OBJECTIVES:
            raise ValueError(f"unknown objective {objective!r}; choose one of {sorted(OBJECTIVES)}")
        f = svc().facts(property_id) if objective == DEFAULT_OBJECTIVE else \
            svc().scenario(property_id, None, {"objective": objective})
        return f.next_best_action.model_dump(mode="json")

    @app.get("/api/properties/{property_id}/lab")
    def lab(property_id: str, budget: float = 10000, objective: str = DEFAULT_OBJECTIVE):
        """Every feasible package (engine run per package), named plans, interactions, sensitivity."""
        if objective not in OBJECTIVES:
            raise ValueError(f"unknown objective {objective!r}; choose one of {sorted(OBJECTIVES)}")
        if not 0 < budget <= 500000:
            raise ValueError("budget must be between £1 and £500,000")
        return svc().lab(property_id, budget, objective).model_dump(mode="json")

    @app.post("/api/properties/{property_id}/ask")
    def ask(property_id: str, req: AskRequest):
        """What-if assistant: parse → feasibility → analyse_home reruns → gated explanation."""
        base = svc().facts(property_id)
        it = interpret(req.question, base)
        if not it.understood:
            return {"interpretation": it.model_dump(), "facts": None, "explanation": None}
        f = svc().scenario(property_id, Scenario(name="Your what-if", measures=it.measures),
                           {"objective": req.objective, "declined_measures": it.declined,
                            "completed_measures": it.completed})
        return {"interpretation": it.model_dump(), "facts": f.model_dump(mode="json"),
                "explanation": explain(f, "package").model_dump()}

    @app.get("/api/properties/{property_id}/gate-demo")
    def gate_demo(property_id: str):
        """Show the gate passing the honest explanation and blocking three corrupted versions."""
        f = svc().facts(property_id)
        clean = explain_package(f).text
        if f.package is None:
            return {"cases": [], "note": "No package for this home, so nothing to corrupt."}
        im = f.package.impact
        fuel = "electricity" if (im.electricity.saving_kwh or 0) != 0 else "gas"
        sav = getattr(im, fuel).saving_kwh
        cases = [
            ("Honest template explanation", clean),
            ("An invented number", clean + f" It will also save you about {abs(im.net_saving_kwh) * 1.37:,.0f} kWh more next year."),
            ("A flipped direction", f"This package {'raises' if sav > 0 else 'cuts'} {fuel} by {abs(sav):,.0f} kWh a year."),
            ("A causal value promise", clean + " This will increase your home's value."),
        ]
        return {"cases": [{"label": lab, "text": t, "gate": gate_check(t, f, "package").model_dump()} for lab, t in cases]}

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
        return {"facts": f.model_dump(mode="json"), "explanation": explain(f, "package").model_dump()}

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
