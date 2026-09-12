"""Local HTTP API. Run with uvicorn chronoverse.api:app --host 127.0.0.1."""
from contextlib import asynccontextmanager
import os
import re
from pathlib import Path

from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import Field, ValidationError
from starlette.datastructures import Headers
from starlette.middleware.trustedhost import TrustedHostMiddleware
from mcp.server.transport_security import RequestBodyLimitMiddleware

from .models import AssertionInput, EventInput, QueryRequest, InputModel
from .profiles import ProfileManager
from .imports import ImportService, ImportLimitError, MAX_UPLOAD_BYTES, TEMPLATES

ROOT = Path(__file__).resolve().parents[2]


def default_db_path():
    return os.getenv("CHRONOVERSE_DB", str(ROOT / "data" / "chronoverse.sqlite3"))


class LocalTrustedHostMiddleware(TrustedHostMiddleware):
    """Preserve bracketed IPv6; Starlette 1.6 splits Host at the first colon."""
    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            host = Headers(scope=scope).get("host", "")
            if host.startswith("["):
                match = re.fullmatch(r"(\[[0-9a-fA-F:.]+\])(?::[0-9]+)?", host)
                if match and (self.allow_any or match.group(1) in self.allowed_hosts):
                    return await self.app(scope, receive, send)
                return await PlainTextResponse("Invalid host header", status_code=400)(scope, receive, send)
        return await super().__call__(scope, receive, send)


class ProfileCreate(InputModel):
    name: str = Field(min_length=1, max_length=100)


class ImportCommit(InputModel):
    preview_id: str = Field(pattern=r"^pv-[0-9a-f]{32}$")


def create_app(db_path=None, *, allowed_hosts=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.profiles = ProfileManager(db_path or default_db_path())
        app.state.store = app.state.profiles.get_store("demo")
        app.state.imports = ImportService(app.state.profiles)
        try:
            yield
        finally:
            app.state.profiles.close()

    app = FastAPI(title="Chronoverse", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:4173", "http://127.0.0.1:4173"], allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    app.add_middleware(RequestBodyLimitMiddleware, max_body_size=MAX_UPLOAD_BYTES + 64 * 1024)

    trusted_hosts = allowed_hosts if allowed_hosts is not None else [
        host.strip() for host in os.getenv("CHRONOVERSE_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",") if host.strip()
    ]
    app.add_middleware(LocalTrustedHostMiddleware, allowed_hosts=trusted_hosts, www_redirect=False)

    @app.exception_handler(ImportLimitError)
    async def too_large(request, exc):
        return JSONResponse(status_code=413, content={"detail":str(exc)})

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse(status_code=404, content={"detail": str(exc).strip("'")})

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse(status_code=409 if "already exists" in str(exc) else 422, content={"detail": str(exc)})

    @app.exception_handler(RuntimeError)
    async def unavailable(request, exc):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/profiles")
    def profiles(request: Request):
        return {"profiles":request.app.state.profiles.list_profiles(),"default_profile_id":"demo"}

    @app.post("/api/profiles", status_code=201)
    def create_profile(value: ProfileCreate, request: Request):
        return request.app.state.profiles.create_profile(value.name)

    @app.get("/api/meta")
    def meta(request: Request, profile_id: str = "demo", known_at: str | None = None):
        return request.app.state.profiles.meta(profile_id, known_at=known_at)

    @app.post("/api/query")
    def search(value: QueryRequest, request: Request, profile_id: str = "demo"):
        return request.app.state.profiles.query(profile_id, value)

    @app.get("/api/assertions")
    def assertions(request: Request, query: str = "", valid_at: str | None = None, known_at: str | None = None, world: str = "main", plane: str = "all", perspective: str = "all", limit: int = Query(default=20, ge=1, le=100), include_retired: bool = False, profile_id: str = "demo"):
        data = dict(query=query,world=world,plane=plane,perspective=perspective,limit=limit,include_retired=include_retired)
        data.update({key:value for key,value in dict(valid_at=valid_at,known_at=known_at).items() if value is not None})
        try:
            value = QueryRequest(**data)
        except ValidationError as exc:
            raise RequestValidationError(exc.errors()) from exc
        return request.app.state.profiles.query(profile_id,value)

    @app.get("/api/assertions/{assertion_id}")
    def detail(assertion_id: str, request: Request, known_at: str | None = None, valid_at: str | None = None, profile_id: str = "demo"):
        manager=request.app.state.profiles
        scope=manager.default_scope(profile_id)
        value=manager.get_store(profile_id).get_assertion(assertion_id,known_at=known_at or scope["known_at"],valid_at=valid_at or scope["valid_at"])
        return {**value,"profile_id":profile_id}

    @app.post("/api/assertions", status_code=201)
    def create(value: AssertionInput, request: Request, profile_id: str = "demo"):
        return {**request.app.state.profiles.get_store(profile_id).add_assertion(value),"profile_id":profile_id}

    @app.post("/api/assertions/{assertion_id}/events", status_code=201)
    def event(assertion_id: str, value: EventInput, request: Request, profile_id: str = "demo"):
        return {**request.app.state.profiles.get_store(profile_id).add_event(assertion_id,value),"profile_id":profile_id}

    @app.post("/api/evaluate")
    def evaluate(request: Request, profile_id: str = "demo"):
        request.app.state.profiles.get_profile(profile_id)
        value=request.app.state.profiles.get_store("demo").evaluate()
        return {**value,"profile_id":profile_id,"evaluation_profile_id":"demo"}

    @app.post("/api/imports/preview")
    async def preview_import(request: Request, file: UploadFile = File(...), profile_id: str = "demo"):
        request.app.state.profiles.get_profile(profile_id)
        try:
            content=await file.read(MAX_UPLOAD_BYTES+1)
        finally:
            await file.close()
        # Run PDF worker/subprocess and validation away from the event loop.
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(request.app.state.imports.preview,profile_id,file.filename,content)

    @app.post("/api/imports/commit")
    def commit_import(value: ImportCommit, request: Request, profile_id: str = "demo"):
        return request.app.state.imports.commit(profile_id,value.preview_id)

    @app.get("/api/imports/templates/{format}")
    def import_template(format: str):
        if format not in TEMPLATES:
            raise KeyError("Import template not found")
        media_type,content=TEMPLATES[format]
        return Response(content,media_type=media_type,headers={"Content-Disposition":f'attachment; filename="chronoverse-example.{format}"'})

    frontend = Path(os.getenv("CHRONOVERSE_STATIC_DIR", str(ROOT / "frontend" / "dist")))
    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="workbench")
    return app


app = create_app()
