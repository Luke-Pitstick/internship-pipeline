#!/usr/bin/env python3
# ruff: noqa: E501
"""A local, read-only view of the Render internship worker."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DEFAULT_ADDRESS = "srv-db228lqjnfac73ekr0q0@ssh.oregon.render.com"
SSH_ADDRESS = re.compile(r"[a-zA-Z0-9_-]+@ssh\.[a-z0-9-]+\.render\.com")
MAX_RESPONSE_BYTES = 1024 * 1024

# Fixed trusted code. Candidate data stays remote; credentials are never opened.
# SQLite opens in read-only mode; deterministic screening makes no provider calls.
REMOTE_SCRIPT = r"""
import json, sqlite3, time, urllib.request
from pathlib import Path
ROOT = Path("/var/data")
PROC = Path("/proc")
RENDERER_URL = "http://internship-resume-matcher:3000/api/v1/health"
now = time.time()
roles = {role: False for role in ("collector", "matcher", "resumes", "delivery", "discovery")}
for path in PROC.glob("[0-9]*/cmdline"):
    try:
        args = path.read_bytes().split(b"\0")
        if not any(b"internship_pipeline.cli" == arg or arg.endswith(b"/internship-pipeline")
                   for arg in args):
            continue
        for i, arg in enumerate(args[:-1]):
            if arg == b"worker":
                role = args[i+1].decode("ascii", errors="ignore")
                if role in roles:
                    roles[role] = True
    except OSError:
        pass
readiness = {name: (ROOT / path).is_file() for name, path in {
    "activated": "activated", "settings": "config/settings.yaml",
    "companies": "config/companies.yaml", "profile": "private/profile.yaml",
    "master_pdf": "private/master-resume.pdf", "codex_auth": "codex/auth.json",
}.items()}
result = {"observed_at": now, "readiness": readiness, "roles": roles,
          "database": "missing", "counts": {}, "queues": [], "sources": [],
          "source_summary": {}, "recent_jobs": [], "oldest_work_age_seconds": None,
          "renderer": "unavailable", "relevance": {
              "status": "unavailable", "screened": 0, "limit": 1000, "accepted": 0}}
try:
    with urllib.request.urlopen(RENDERER_URL, timeout=3) as response:
        if response.status == 200:
            result["renderer"] = "healthy"
except (OSError, ValueError):
    pass
db = ROOT / "pipeline.sqlite3"
if db.is_file():
    try:
        with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=2) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            deadline = time.monotonic() + 3
            connection.set_progress_handler(lambda: time.monotonic() > deadline, 10000)
            for table in ("jobs", "matches", "artifacts", "deliveries", "candidates"):
                result["counts"][table] = connection.execute(
                    "SELECT COUNT(*) FROM " + table).fetchone()[0]
            result["queues"] = [dict(row) for row in connection.execute(
                "SELECT kind,status,COUNT(*) count FROM tasks GROUP BY kind,status "
                "ORDER BY kind,status")]
            oldest = connection.execute("SELECT MIN(created) FROM tasks "
                "WHERE status IN ('pending','running')").fetchone()[0]
            result["oldest_work_age_seconds"] = None if oldest is None else max(0, int(now-oldest))
            summary = connection.execute("SELECT COUNT(*) total, "
                "COALESCE(SUM(enabled),0) enabled, "
                "COALESCE(SUM(enabled AND failures>0),0) failing, "
                "COALESCE(SUM(enabled AND next_due<?),0) overdue, "
                "MAX(last_success) last_success FROM targets", (now-60,)).fetchone()
            result["source_summary"] = dict(summary)
            result["sources"] = [dict(row) for row in connection.execute(
                "SELECT id,kind,provider,enabled,last_attempt,last_success,next_due,failures,complete "
                "FROM targets ORDER BY enabled DESC,failures DESC,next_due LIMIT 100")]
            result["database"] = "readable"
            if not readiness["profile"]:
                result["relevance"]["status"] = "profile_missing"
            else:
                try:
                    from internship_pipeline.config import load_profile
                    from internship_pipeline.matching import _deterministic_match, _INTERNSHIP
                    from internship_pipeline.models import Job
                    profile = load_profile(ROOT / "private/profile.yaml")
                    relevant, screened, accepted = [], 0, 0
                    for row in connection.execute(
                            "SELECT data,status,first_seen,last_seen FROM jobs WHERE status='open' "
                            "ORDER BY first_seen DESC LIMIT 1000"):
                        job = Job.model_validate_json(row["data"])
                        screened += 1
                        match = _deterministic_match(job, profile)
                        confirmed_internship = bool(_INTERNSHIP.search(job.posting.title)) or bool(
                            _INTERNSHIP.fullmatch(job.posting.employment_type or ""))
                        if not match.accepted or not match.fact_ids or not confirmed_internship:
                            continue
                        accepted += 1
                        if len(relevant) < 20:
                            relevant.append({
                                "company": job.posting.company[:200],
                                "title": job.posting.title[:300],
                                "status": row["status"], "event": job.event[:30],
                                "first_seen": row["first_seen"], "last_seen": row["last_seen"],
                                "source_timestamp": (job.posting.published_at.isoformat()
                                                     if job.posting.published_at else None),
                                "timestamp_kind": (job.posting.timestamp_kind if
                                    job.posting.timestamp_kind in {"published", "updated",
                                        "aggregator_date", "source_time_ambiguous", "unknown"}
                                    else "unknown"),
                                "fit": match.fit, "review_questions": len(match.unknowns),
                                "role_family": match.role_family.value,
                            })
                    result["recent_jobs"] = relevant
                    result["relevance"].update(status="ready", screened=screened, accepted=accepted)
                except Exception:
                    # A private profile or matcher failure must never reveal raw listings as fits.
                    result["recent_jobs"] = []
                    result["relevance"].update(status="unavailable", screened=0, accepted=0)
    except (sqlite3.Error, ValueError, TypeError, AttributeError):
        result.update(database="unreadable", counts={}, queues=[], sources=[],
                      source_summary={}, recent_jobs=[], oldest_work_age_seconds=None)
print(json.dumps(result, allow_nan=False))
"""


def fetch_snapshot(address: str) -> dict[str, Any]:
    if not SSH_ADDRESS.fullmatch(address):
        raise ValueError("Expected USER@ssh.REGION.render.com")
    command = [
        "ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "ServerAliveInterval=5",
        "-o",
        "ServerAliveCountMax=1",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "--",
        address,
        "/app/.venv/bin/python",
        "-",
    ]
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(
            command,
            input=REMOTE_SCRIPT.encode(),
            stdout=output,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
        )
        if result.returncode:
            raise RuntimeError("SSH unavailable; check Render access and your SSH key")
        output.seek(0, os.SEEK_END)
        if output.tell() > MAX_RESPONSE_BYTES:
            raise ValueError("Snapshot exceeds size limit")
        output.seek(0)
        snapshot = json.load(output)
    if not isinstance(snapshot, dict) or set(snapshot) != {
        "observed_at",
        "readiness",
        "roles",
        "database",
        "counts",
        "queues",
        "sources",
        "source_summary",
        "recent_jobs",
        "oldest_work_age_seconds",
        "renderer",
        "relevance",
    }:
        raise ValueError("Unexpected snapshot shape")
    return snapshot


def operational_state(snapshot: dict[str, Any]) -> tuple[str, str]:
    ready = snapshot["readiness"]
    if not ready["activated"]:
        return "waiting", "The worker is deployed and waiting for activation."
    if not all(ready.values()):
        return "blocked", "An expected provisioning file is missing."
    if not all(snapshot["roles"].values()) or snapshot["database"] != "readable":
        return (
            "inactive",
            "Activation exists, but all five workers and readable state are unconfirmed.",
        )
    if snapshot["source_summary"].get("enabled", 0) == 0:
        return "idle", "Workers are present; no source boards are enabled yet."
    failed = any(row["status"] == "failed" and row["count"] for row in snapshot["queues"])
    if snapshot["renderer"] != "healthy":
        return "degraded", "Workers are present, but the private PDF renderer health check failed."
    if snapshot["relevance"]["status"] != "ready":
        return "degraded", "Workers are present, but profile matching could not be verified."
    if failed or any(snapshot["source_summary"].get(key, 0) for key in ("failing", "overdue")):
        return (
            "degraded",
            "Workers are present, but failed work or delayed source checks need attention.",
        )
    return "monitoring", "All five worker processes are present and source checks are scheduled."


class SnapshotCache:
    def __init__(self, address: str) -> None:
        self.address = address
        self.lock = threading.Lock()
        self.last_attempt = float("-inf")
        self.snapshot: dict[str, Any] | None = None
        self.error: str | None = None

    def get(self, *, refresh: bool = False) -> dict[str, Any]:
        with self.lock:
            elapsed = time.monotonic() - self.last_attempt
            if elapsed >= (5 if refresh else 25):
                self.last_attempt = time.monotonic()
                try:
                    self.snapshot = fetch_snapshot(self.address)
                    self.error = None
                except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
                    self.error = "Could not read Render over SSH. Check the service and SSH access."
            age = (
                None
                if self.snapshot is None
                else max(0, int(time.time() - self.snapshot["observed_at"]))
            )
            if self.error or self.snapshot is None:
                state, message = "offline", self.error or "No snapshot is available."
            else:
                state, message = operational_state(self.snapshot)
            if not self.error and age is not None and age > 90:
                state, message = "stale", "This snapshot is older than 90 seconds."
            return {
                "state": state,
                "message": message,
                "snapshot_age_seconds": age,
                "snapshot": self.snapshot,
                "connection": "offline" if self.error else "online",
            }


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Internship pipeline · Render</title><style>
:root{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,sans-serif;background:#10151c;color:#e7edf5}
body{margin:0}main{max-width:1180px;padding:42px 28px 70px;margin:auto}h1{font-size:32px;letter-spacing:-1px;margin:0}
p{color:#9eacbc;line-height:1.6}.eyebrow{font-size:12px;text-transform:uppercase;letter-spacing:2px;color:#9baabd}
header{display:flex;align-items:center;justify-content:space-between;gap:20px}button{background:#e0eaf6;border:0;color:#132333;padding:12px 18px;border-radius:8px;font:inherit;cursor:pointer}
button:disabled{opacity:.5}.panel{margin-top:22px;padding:22px;background:#17202b;border:1px solid #283543;border-radius:12px}
.state{display:inline-block;border-radius:20px;padding:5px 12px;background:#324253;font-size:13px;text-transform:capitalize}
.monitoring{background:#163d35;color:#9ae4bc}.degraded,.blocked,.inactive,.stale{background:#4a351c;color:#ffd495}.offline{background:#4c2830;color:#ffb7bf}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:22px}.metric{background:#17202b;border:1px solid #283543;border-radius:10px;padding:20px}.metric span{display:block;color:#9eacbc;font-size:13px}.metric strong{font-size:29px;display:block;margin-top:6px}
h2{font-size:17px;margin:0 0 16px}table{border-collapse:collapse;width:100%;font-size:13px}th{text-align:left;color:#99a9bb;font-weight:500}th,td{padding:12px 10px;border-bottom:1px solid #293443;vertical-align:top}td:first-child{font-weight:500}tr:last-child td{border:0}.scroll{overflow:auto}.checks{display:flex;gap:9px;flex-wrap:wrap}.check{padding:8px 11px;background:#233040;border-radius:6px;font-size:13px}.present{color:#9ae4bc}.missing{color:#ffd495}.muted{font-size:12px;color:#9eacbc}.notice{margin-bottom:0}.row{display:grid;grid-template-columns:1fr 1fr;gap:22px}@media(max-width:750px){.row{grid-template-columns:1fr}header{align-items:flex-start}main{padding:28px 16px}h1{font-size:25px}}
</style></head><body><main><header><div><div class="eyebrow">Read-only · Render worker</div><h1>Internship pipeline</h1><p>Collection, matching, resumes, and delivery — in one view.</p></div><button id="refresh">Refresh now</button></header>
<div class="panel"><span id="state" class="state">Connecting</span><p id="message">Reading the worker over SSH…</p><div id="updated" class="muted"></div></div>
<div id="metrics" class="metrics"></div><div class="row"><section class="panel"><h2>Provisioning</h2><div id="readiness" class="checks"></div><p class="muted notice">File presence only. A login file does not confirm a valid subscription session. Candidate data stays on Render; credentials are never read.</p></section><section class="panel"><h2>Worker processes</h2><div id="roles" class="checks"></div><p class="muted notice">Process presence shows workers are running; it does not prove a successful model call or end-to-end delivery.</p></section></div>
<section class="panel"><h2>Work queues</h2><div id="queue" class="scroll"></div><p id="oldest" class="muted notice"></p></section>
<section class="panel"><h2>Source checks</h2><p id="coverage" class="muted"></p><div id="sources" class="scroll"></div></section>
<section class="panel"><h2>Internships matching your profile</h2><p id="relevance" class="muted">Reading preliminary matches…</p><p class="muted">Only internships with supported candidate skills and no confirmed eligibility conflict appear here. These are preliminary rules-based matches, with remaining questions to review. Collected listings are not recommendations.</p><div id="jobs" class="scroll"><p>No verified profile matches to show yet.</p></div><p class="muted">Source timestamps may describe publication, an update, or an aggregator date. Ambiguous dates are not confirmed publication times.</p></section>
<p class="muted">Auto-refreshes every 30 seconds while this page is open. Render state is read-only. Local Dot relay and Google Sheets delivery are outside this view.</p>
</main><script>
const el=id=>document.getElementById(id), text=(tag,value)=>{const n=document.createElement(tag);n.textContent=value;return n;};
const when=value=>value===null||value===undefined?'Never':new Date(typeof value==='number'?value*1000:value).toLocaleString();
const sourceTime=j=>j.source_timestamp?`${when(j.source_timestamp)} · ${({published:'Published (source-reported)',updated:'Updated',aggregator_date:'Aggregator date',source_time_ambiguous:'Ambiguous (published or updated)',unknown:'Kind unknown'})[j.timestamp_kind]||'Kind unknown'}`:'Unknown';
function table(id,headers,rows){const root=el(id);root.replaceChildren();if(!rows.length){root.append(text('p','No records yet.'));return;}const t=document.createElement('table'),h=document.createElement('tr');headers.forEach(v=>h.append(text('th',v)));const head=document.createElement('thead');head.append(h);t.append(head);const body=document.createElement('tbody');rows.forEach(values=>{const r=document.createElement('tr');values.forEach(v=>r.append(text('td',v)));body.append(r);});t.append(body);root.append(t);}
function checks(id,data,labels){el(id).replaceChildren();Object.entries(data||{}).forEach(([key,value])=>{const n=text('span',`${value?'✓':'—'} ${labels?.[key]||key}`);n.className=`check ${value?'present':'missing'}`;el(id).append(n);});}
function render(data){el('state').textContent=data.state;el('state').className=`state ${data.state}`;el('message').textContent=data.message;el('updated').textContent=data.snapshot?`${data.connection==='offline'?'Last known data · ':''}Observed ${when(data.snapshot.observed_at)} · ${data.snapshot_age_seconds}s ago · ${data.connection==='offline'?'Stale: SSH offline':data.snapshot_age_seconds>90?'Stale: older than 90s':'Current snapshot (under 90s)'}`:'No successful snapshot yet.';const s=data.snapshot;if(!s)return;
checks('readiness',s.readiness,{activated:'Activation',settings:'Settings',companies:'Companies',profile:'Profile',master_pdf:'Master PDF',codex_auth:'Codex login'});checks('roles',s.roles);el('metrics').replaceChildren();Object.entries({...s.counts,relevant:s.relevance.status==="ready"?s.relevance.accepted:"Unavailable",renderer:s.renderer}).forEach(([key,value])=>{const n=document.createElement('div');n.className='metric';n.append(text('span',({artifacts:'Stored artifacts',deliveries:'Recorded deliveries',candidates:'Discovery candidates',matches:'Stored matches',jobs:'Raw collected listings',relevant:'Preliminary matches in scope',renderer:'PDF renderer'})[key]||key),text('strong',value));el('metrics').append(n);});
table('queue',['Role / task','State','Count'],s.queues.map(q=>[q.kind,q.status,q.count]));el('oldest').textContent=s.oldest_work_age_seconds===null?'No pending or running work.':`Oldest pending or running work: ${s.oldest_work_age_seconds}s.`;const sum=s.source_summary;el('coverage').textContent=s.database==='readable'?`${sum.enabled||0} enabled / ${sum.total||0} total · ${sum.failing||0} failing · ${sum.overdue||0} overdue by more than 60s · showing up to 100 sources`:`Database: ${s.database}`;
table('sources',['Source','Provider','Last attempt','Last success','Next due','Failures','Coverage'],s.sources.map(s=>[s.id,s.provider,when(s.last_attempt),when(s.last_success),s.enabled?when(s.next_due):'Disabled',s.failures,s.complete?'Complete':'Unconfirmed / partial']));el('relevance').textContent=s.relevance.status==='ready'?`${s.relevance.accepted} preliminary matches among ${s.relevance.screened} screened open listings (newest ${s.relevance.limit} maximum); showing up to 20. First seen is observation time; source timestamps retain their reported kind. Backlog is initial inventory.`:s.relevance.status==='profile_missing'?'Matching is unavailable until your profile is provisioned.':'Matching could not be verified. No listings are presented as recommendations.';table('jobs',['Company / role','Preliminary fit','Review questions','Event','First seen','Last observed','Source timestamp'],s.recent_jobs.map(j=>[`${j.company} · ${j.title}`,`${j.role_family} · ${j.fit}`,j.review_questions?`${j.review_questions} to confirm`:'None flagged by rules',j.event,when(j.first_seen),when(j.last_seen),sourceTime(j)]));if(!s.recent_jobs.length)el('jobs').replaceChildren(text('p','No verified profile matches to show yet.'));}
let busy=false;async function refresh(manual=false){if(busy)return;busy=true;el('refresh').disabled=true;try{const r=await fetch(`/api/status${manual?'?refresh=1':''}`,{cache:'no-store'});if(!r.ok)throw new Error('Unavailable');render(await r.json());}catch(_){el('state').textContent='Offline';el('state').className='state offline';el('message').textContent='The local dashboard server is unavailable. Previously displayed data is stale.';}finally{busy=false;el('refresh').disabled=false;}}
el('refresh').addEventListener('click',()=>refresh(true));refresh();setInterval(()=>refresh(),30000);
</script></body></html>"""


def make_handler(cache: SnapshotCache) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            port = self.server.server_port  # type: ignore[attr-defined]
            if self.headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
                self.send_error(403)
                return
            if self.path == "/":
                content, mime = HTML.encode(), "text/html; charset=utf-8"
            elif self.path in {"/api/status", "/api/status?refresh=1"}:
                content = json.dumps(cache.get(refresh=self.path.endswith("?refresh=1"))).encode()
                mime = "application/json"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; script-src 'unsafe-inline'; "
                "style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; "
                "frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, _format: str, *args: Any) -> None:
            pass

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-address", default=DEFAULT_ADDRESS)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not SSH_ADDRESS.fullmatch(args.ssh_address):
        parser.error("Expected USER@ssh.REGION.render.com")
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port), make_handler(SnapshotCache(args.ssh_address))
    )
    print(f"Dashboard: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
