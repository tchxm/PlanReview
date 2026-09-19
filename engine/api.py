from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
from engine.pipeline import Pipeline, LOCK, ROOT
from engine.exceptions import PlanReviewError

app = FastAPI(title="PlanReview", version="0.1.0")
app.add_middleware(
    TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
)
pipeline = Pipeline()


@app.middleware("http")
async def local_origin(request, call_next):
    origin = request.headers.get("origin")
    if (
        request.method not in {"GET", "HEAD", "OPTIONS"}
        and origin
        and origin
        not in {
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        }
    ):
        return JSONResponse(
            {"detail": "Cross-origin mutation blocked"}, status_code=403
        )
    return await call_next(request)


class TaskInput(BaseModel):
    task: str = Field(min_length=1, max_length=4000)
    mode: str = "replay"


def call(fn, *args):
    try:
        with LOCK:
            return fn(*args)
    except PlanReviewError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": exc.code, "message": exc.message, "details": exc.details},
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    except (OSError, TimeoutError) as exc:
        raise HTTPException(503, f"Pipeline incomplete: {exc}")


@app.get("/api/health")
def health():
    return {"status": "ok", "evaluator": "cedar", "cloud_apply": False}


@app.get("/api/tasks")
def tasks():
    return pipeline.store.list()


@app.post("/api/tasks")
def create(body: TaskInput):
    return call(pipeline.create, body.task, body.mode)


@app.get("/api/tasks/{id}")
def get(id: str):
    return call(pipeline.store.get, id)


@app.get("/api/tasks/{id}/intent")
def intent(id: str):
    t = call(pipeline.store.get, id)
    return t.get("intent")


@app.post("/api/tasks/{id}/confirm")
def confirm(id: str, body: dict | None = None):
    return call(pipeline.confirm, id, body)


@app.post("/api/tasks/{id}/agent")
def agent(id: str, variant: str = "poisoned"):
    return call(pipeline.agent, id, variant)


@app.post("/api/tasks/{id}/plan")
def plan(id: str):
    return call(pipeline.plan, id)


@app.post("/api/tasks/{id}/canonicalize")
def canonical(id: str):
    return call(pipeline.canonicalize, id)


@app.post("/api/tasks/{id}/evaluate")
def evaluate(id: str):
    return call(pipeline.evaluate, id)


@app.post("/api/tasks/{id}/resolve")
def resolve(id: str, body: dict[str, str]):
    return call(pipeline.resolve, id, body)


@app.post("/api/tasks/{id}/apply")
def apply(id: str):
    return call(pipeline.apply, id)


@app.get("/api/tasks/{id}/audit")
def audit(id: str):
    return call(pipeline.store.audit, id)


if (ROOT / "web/dist").exists():
    app.mount("/", StaticFiles(directory=ROOT / "web/dist", html=True), name="console")
