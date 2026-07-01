from __future__ import annotations

import json
import queue
import threading
import uuid
from pathlib import Path
from typing import Dict

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import load_settings
from .main import audit_lead
from .models import LeadInput, model_to_dict


app = FastAPI(title="Website Lead Auditor")
settings = load_settings()
settings.output_dir.mkdir(parents=True, exist_ok=True)
settings.screenshots_dir.mkdir(parents=True, exist_ok=True)
app.mount("/outputs", StaticFiles(directory=str(settings.output_dir)), name="outputs")

jobs: Dict[str, "queue.Queue[dict]"] = {}


class AuditRequest(BaseModel):
    website: str
    business_name: str = "Manual Test Lead"
    business_category: str = ""
    phone: str = ""
    email: str = ""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Website Lead Auditor</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, sans-serif; margin: 0; background: #f7f7f8; color: #1f2937; }
    main { max-width: 1200px; margin: 0 auto; padding: 24px; }
    form { display: grid; grid-template-columns: 2fr 1fr 1fr auto; gap: 10px; margin-bottom: 18px; }
    input, button { font: inherit; padding: 10px 12px; border: 1px solid #d1d5db; border-radius: 6px; }
    button { background: #111827; color: white; cursor: pointer; }
    .grid { display: grid; grid-template-columns: minmax(0, 1fr) 380px; gap: 16px; align-items: start; }
    #logs, #result, #prompt { background: white; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; overflow: auto; }
    #logs { height: 560px; }
    .event { border-bottom: 1px solid #eee; padding: 8px 0; }
    .event strong { color: #111827; }
    pre { white-space: pre-wrap; word-break: break-word; margin: 6px 0 0; font-size: 12px; }
    img { max-width: 100%; border: 1px solid #ddd; border-radius: 6px; margin: 8px 0; background: white; }
    h1 { margin: 0 0 16px; font-size: 24px; }
    h2 { font-size: 16px; margin: 0 0 8px; }
    @media (max-width: 850px) { form, .grid { grid-template-columns: 1fr; } #logs { height: 420px; } }
  </style>
</head>
<body>
<main>
  <h1>Website Lead Auditor</h1>
  <form id="form">
    <input id="website" placeholder="https://example.com" required>
    <input id="business_name" placeholder="Business name">
    <input id="business_category" placeholder="Category">
    <button>Begin audit</button>
  </form>
  <div class="grid">
    <section>
      <h2>Live Logs</h2>
      <div id="logs"></div>
    </section>
    <aside>
      <h2>Screenshots</h2>
      <div id="shots"></div>
      <h2>LLM Prompt / Response</h2>
      <div id="prompt"></div>
      <h2>Final Result</h2>
      <div id="result"></div>
    </aside>
  </div>
</main>
<script>
const form = document.getElementById('form');
const logs = document.getElementById('logs');
const result = document.getElementById('result');
const promptBox = document.getElementById('prompt');
const shots = document.getElementById('shots');

function addLog(event, payload) {
  const div = document.createElement('div');
  div.className = 'event';
  div.innerHTML = `<strong>${event}</strong><pre>${JSON.stringify(payload, null, 2)}</pre>`;
  logs.appendChild(div);
  logs.scrollTop = logs.scrollHeight;
  if (event === 'llm.request') {
    promptBox.innerHTML = `<pre>${payload.prompt || ''}</pre>`;
  }
  if (event === 'llm.response') {
    promptBox.innerHTML += `<pre>${payload.raw_response || ''}</pre>`;
  }
  if (event === 'screenshot.saved') {
    shots.innerHTML = '';
    (payload.paths || []).forEach(path => {
      const rel = '/outputs/' + path.split(/outputs[\\\\/]/).pop().replaceAll('\\\\', '/');
      const img = document.createElement('img');
      img.src = rel;
      img.alt = path;
      shots.appendChild(img);
    });
  }
  if (event === 'lead.result') {
    result.innerHTML = `<pre>${JSON.stringify(payload, null, 2)}</pre>`;
  }
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  logs.innerHTML = '';
  result.innerHTML = '';
  promptBox.innerHTML = '';
  shots.innerHTML = '';
  const body = {
    website: document.getElementById('website').value,
    business_name: document.getElementById('business_name').value || 'Manual Test Lead',
    business_category: document.getElementById('business_category').value || ''
  };
  const res = await fetch('/api/audit/start', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const data = await res.json();
  const source = new EventSource(`/api/audit/${data.job_id}/events`);
  source.onmessage = (msg) => {
    const item = JSON.parse(msg.data);
    addLog(item.event, item.payload);
    if (item.event === 'job.done') source.close();
  };
});
</script>
</body>
</html>
"""


@app.post("/api/audit/start")
def start_audit(request: AuditRequest) -> dict:
    job_id = uuid.uuid4().hex
    events: "queue.Queue[dict]" = queue.Queue()
    jobs[job_id] = events

    def emit(event: str, payload: dict) -> None:
        events.put({"event": event, "payload": payload})

    def worker() -> None:
        try:
            lead = LeadInput(
                business_name=request.business_name,
                business_category=request.business_category,
                website=request.website,
                phone=request.phone,
                email=request.email,
            )
            result = audit_lead(lead, settings, emit)
            emit("job.done", model_to_dict(result))
        except Exception as exc:
            emit("job.error", {"error": str(exc)})
            emit("job.done", {})

    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/audit/{job_id}/events")
def stream_events(job_id: str) -> StreamingResponse:
    events = jobs.get(job_id)
    if events is None:
        events = queue.Queue()
        events.put({"event": "job.error", "payload": {"error": "Unknown job"}})
        events.put({"event": "job.done", "payload": {}})

    def generator():
        while True:
            item = events.get()
            yield f"data: {json.dumps(item, default=str)}\n\n"
            if item.get("event") == "job.done":
                jobs.pop(job_id, None)
                break

    return StreamingResponse(generator(), media_type="text/event-stream")
