"""
Vercel ASGI entrypoint (FastAPI).

The Streamlit dashboard is not run on Vercel (serverless). Use locally:
  streamlit run dashboard.py
Or deploy the UI with Streamlit Community Cloud / Docker / Railway, etc.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(
    title="Ignis-Twin",
    description="API shell for Vercel. Pipeline and map UI run outside serverless.",
    version="0.1.0",
)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def root() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Ignis-Twin</title></head>
<body style="font-family:system-ui,sans-serif;max-width:42rem;margin:2rem auto;padding:0 1rem;line-height:1.55">
<h1 style="font-weight:650;letter-spacing:-0.02em">Ignis-Twin</h1>
<p>This deployment is a <strong>lightweight FastAPI</strong> shell so Vercel has a valid Python entrypoint.</p>
<p>The <strong>interactive map</strong> is a <strong>Streamlit</strong> app: run it on your machine with
<code style="background:#f4f4f5;padding:0.15em 0.4em;border-radius:4px">streamlit run dashboard.py</code>
(after <code style="background:#f4f4f5;padding:0.15em 0.4em;border-radius:4px">pip install -r requirements-ui.txt</code>).</p>
<p>The heavy pipeline (FIRMS, SAR, rasters) uses <code>requirements.txt</code> and is intended for local or VM / container runs, not this serverless function.</p>
<p><a href="/health">/health</a> · <a href="/docs">OpenAPI</a></p>
</body></html>"""


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ignis-twin"}
