"""Real owner API, Google auth/HTTP adapter and queue worker with synthetic Google responses."""
import json
import re
import sys
import tempfile
import threading
from pathlib import Path
import httpx
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"src"))
from internship_pipeline.app import create_app,runtime_settings
from internship_pipeline.models import FetchResult,SourceJob
from internship_pipeline.storage import Store
from internship_pipeline.sheets_provider import GoogleSheets
with tempfile.TemporaryDirectory(prefix="pipeline-sheets-browser-") as directory:
    root=Path(directory);settings=runtime_settings(root,None)
    app=create_app(root,origin="http://127.0.0.1:4179",static_dir=Path("build").resolve(),settings=settings)
    store=Store(settings.database_path);store.register_target("synthetic","company","{}","synthetic")
    job=store.ingest("synthetic",FetchResult(jobs=[SourceJob(source="synthetic",board_id="synthetic",source_id="1",company="=UNTRUSTED()",title="Synthetic Internship",description="Synthetic job",apply_url="https://example.test/apply")]),"p1")[0]
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    info={"type":"service_account","project_id":"synthetic","private_key_id":"synthetic-key","private_key":key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode(),"client_email":"synthetic@synthetic.iam.gserviceaccount.com","token_uri":"https://oauth2.googleapis.com/token"}
    rows=[["Job ID","Company","Title","Location","Score","Posted","Observed","Deadline","Apply","Source","My notes","Formula","Application status"],[job.id,"","","","","","","","","","Synthetic manual note","=SUM(E2:E3)","applied"]]
    def respond(request):
        if request.url.host=="oauth2.googleapis.com":return httpx.Response(200,json={"access_token":"synthetic-token","expires_in":3600,"token_type":"Bearer"})
        assert request.url.host=="sheets.googleapis.com"
        if request.method=="POST":
            body=json.loads(request.content);assert body["valueInputOption"]=="RAW"
            for data in body["data"]:
                match=re.search(r"!([A-Z]+)([0-9]+)$",data["range"]);column=0
                for char in match[1]:column=column*26+ord(char)-64
                row=int(match[2]);assert column<=10
                while len(rows)<row:rows.append([])
                while len(rows[row-1])<column:rows[row-1].append("")
                rows[row-1][column-1]=data["values"][0][0]
            return httpx.Response(200,json={"totalUpdatedCells":len(body["data"])})
        if "/values/" in request.url.path:return httpx.Response(200,json={"values":rows})
        if request.url.params.get("includeGridData")=="true":return httpx.Response(200,json={"sheets":[{"data":[{"startRow":1,"startColumn":11,"rowData":[{"values":[{"userEnteredValue":{"formulaValue":"=SUM(E2:E3)"}}]}]}]}]})
        return httpx.Response(200,json={"properties":{"title":"Synthetic Opportunities"},"sheets":[{"properties":{"title":"Jobs","sheetId":0,"gridProperties":{"rowCount":1000,"columnCount":52}}}]})
    app.state.sheets_integration.provider_factory=lambda info,sheet:GoogleSheets(info,sheet,transport=httpx.MockTransport(respond))
    Path("test-results-sheets").mkdir(exist_ok=True)
    Path("test-results-sheets/setup.json").write_text(json.dumps({"token":app.state.identity.setup_token(),"service_account":json.dumps(info),"job_id":job.id}))
    stop=threading.Event()
    def work():
        while not stop.is_set():
            if not app.state.sheets_integration.process_next():stop.wait(.2)
    worker=threading.Thread(target=work,daemon=True);worker.start()
    try:uvicorn.run(app,host="127.0.0.1",port=4179,access_log=False)
    finally:stop.set();worker.join(timeout=3)
