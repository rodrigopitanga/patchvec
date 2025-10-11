# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

# pave/ui.py — minimal, crash-proof UI wiring
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from starlette.staticfiles import StaticFiles
from pathlib import Path
import copy

# ultra-simple fallback template (no f-string; plain string -> safe braces)
_FALLBACK_TMPL = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="/favicon.ico" />
<title>__INST_NAME__ • Search</title>
<style>
  :root{ --bg:#f6e6d9; --panel:#fffaf6; --text:#2b1e11; --muted:#6b5b53; --accent:#c9463d; --border:#ead7c7; }
  :root{ --link:#0f2e4d; --link-accent:#14b8a6; }
  @media (prefers-color-scheme: dark){
    :root{ --bg:#1a1410; --panel:#221a14; --text:#f1e9e4; --muted:#b7a9a1; --accent:#ef6b62; --border:#3a2c22; --link:#9dd9d3; --link-accent:#34d399; }
  }
  html,body{height:100%}
  body{margin:0;font:16px/1.45 system-ui,Segoe UI,Roboto,Inter,Arial;background:var(--bg);color:var(--text)}
  .tabs{display:flex;gap:8px;padding:12px;border-bottom:1px solid var(--border);background:var(--panel);align-items:center}
  .tab{padding:8px 12px;border-radius:10px;border:1px solid var(--border);cursor:pointer;background:transparent;color:var(--text)}
  .tab.active{background:var(--link-accent);color:#041318;border-color:var(--link-accent)}
  .desc{color:var(--muted);font-size:.9rem;margin-left:auto;padding:8px 12px}
  .frame{display:none;width:100%;height:calc(100vh - 92px);border:0;background:var(--bg)}
  .frame.active{display:block}
  .footer{display:flex;gap:12px;align-items:center;justify-content:center;padding:10px;color:var(--muted);border-top:1px solid var(--border);background:var(--panel)}
  .footer a{color:var(--link);text-decoration:none}
  .footer a:hover{color:var(--link-accent)}
</style>
</head>
<body>
  <div class="tabs">
    <button class="tab active" data-target="search" data-title="__INST_NAME__ • Search">Search</button>
    <button class="tab" data-target="ingest" data-title="__INST_NAME__ • Ingest">Ingest</button>
    <div class="desc">__INST_DESC__</div>
  </div>
  <iframe id="search" class="frame active" src="/ui/search" title="Search"></iframe>
  <iframe id="ingest" class="frame" src="/ui/ingest" title="Ingest"></iframe>
  <div class="footer">
    <span>patchvec v__VERSION__</span> •
    <a href="__REPO_URL__" target="_blank" rel="noopener">Repository</a> •
    <a href="__LICENSE_URL__" target="_blank" rel="noopener">__LICENSE_NAME__</a>
  </div>
<script>
  const tabs = document.querySelectorAll('.tab');
  const frames = document.querySelectorAll('.frame');
  tabs.forEach(function(tab){
    tab.addEventListener('click', function(){
      tabs.forEach(function(t){ t.classList.remove('active'); });
      frames.forEach(function(f){ f.classList.remove('active'); });
      tab.classList.add('active');
      document.getElementById(tab.dataset.target).classList.add('active');
      document.title = tab.dataset.title || document.title;
    });
  });
</script>
</body></html>
"""

def attach_ui(app, cfg, version):
    # instance strings
    inst_name = str(cfg.get("instance.name"))
    inst_desc = str(cfg.get("instance.desc"))

    # footer links
    repo_url = "https://github.com/flowlexi/patchvec"
    license_name = "Licensed under GNU GPL v3.0"
    license_url = "https://www.gnu.org/licenses/gpl-3.0-standalone.html"

    # reflect on app header
    app.title = inst_name
    app.description = inst_desc

    # static + favicon (hardcoded path relative to this file). never crash if dir missing.
    assets_dir = (Path(__file__).parent / "assets").resolve()
    app.mount("/assets", StaticFiles(directory=str(assets_dir), check_dir=False), name="assets")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return FileResponse(
            str((Path(__file__).parent / "assets" / "patchvec_icon_192.png")\
                .resolve()),
            media_type="image/png",
        )

    # openapi (bearer + repo/license)
    _openapi_cache = {"doc": None}
    def _openapi_full():
        if _openapi_cache["doc"] is None:
            schema = get_openapi(title=app.title, version=version, description=app.description, routes=app.routes)
            comps = schema.setdefault("components", {}).setdefault("securitySchemes", {})
            comps["bearerAuth"] = {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
            schema["security"] = [{"bearerAuth": []}]
            info = schema.setdefault("info", {})
            info["x-repository"] = repo_url
            info["license"] = {"name": license_name, "url": license_url}
            _openapi_cache["doc"] = schema
        return _openapi_cache["doc"]

    def _filter(schema: dict, pred):
        s = copy.deepcopy(schema)
        for path in list(s.get("paths", {}).keys()):
            methods = s["paths"][path]
            for m in list(methods.keys()):
                if not pred(path, methods[m]):
                    methods.pop(m, None)
            if not methods:
                s["paths"].pop(path, None)
        s.pop("tags", None)
        return s

    def _is_search(path: str, _op: dict) -> bool:
        return "/search" in path

    def _is_ingest(path: str, _op: dict) -> bool:
        p = path.lower()
        return ("/documents" in p) or ("/collections" in p and "/search" not in p) or p.endswith("/collections")

    @app.get("/openapi-search.json", include_in_schema=False)
    def openapi_search_only():
        return _filter(_openapi_full(), _is_search)

    @app.get("/openapi-ingest.json", include_in_schema=False)
    def openapi_ingest_only():
        return _filter(_openapi_full(), _is_ingest)

    @app.get("/ui/search", include_in_schema=False)
    def ui_search():
        return get_swagger_ui_html(
            openapi_url="/openapi-search.json",
            title=f"{inst_name} • Search",
            swagger_ui_parameters={"defaultModelsExpandDepth": -1, "displayRequestDuration": True, "docExpansion": "list", "tryItOutEnabled": True},
        )

    @app.get("/ui/ingest", include_in_schema=False)
    def ui_ingest():
        return get_swagger_ui_html(
            openapi_url="/openapi-ingest.json",
            title=f"{inst_name} • Ingest",
            swagger_ui_parameters={"defaultModelsExpandDepth": -1, "displayRequestDuration": True, "docExpansion": "list", "tryItOutEnabled": True},
        )

    # lazy-read template on request (so missing file never kills startup)
    tmpl_path = assets_dir / "ui.html"

    @app.get("/ui", include_in_schema=False)
    def ui_home():
        try:
            html = tmpl_path.read_text(encoding="utf-8")
        except Exception:
            html = _FALLBACK_TMPL
        html = (
            html.replace("__INST_NAME__", inst_name)
                .replace("__INST_DESC__", inst_desc)
                .replace("__VERSION__", str(version))
                .replace("__REPO_URL__", repo_url)
                .replace("__LICENSE_NAME__", license_name)
                .replace("__LICENSE_URL__", license_url)
        )
        return HTMLResponse(html)
        
    @app.get("/", include_in_schema=False)
    def root_redirect():
        return RedirectResponse("/ui", status_code=308)
