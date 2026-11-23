"""Refrax public observatory: fixed-schema read-only data gateway.
No proxy passthrough, filesystem service, command runner, or remote model execution.
Only explicit viewer coordinates are accepted, processed in memory and not logged.
"""
import argparse
import datetime as dt
import json
import math
import os
import re
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ORIGIN=os.environ.get("REFRAX_WEB_ORIGIN","https://niqsaturn.github.io")
UPSTREAM="http://127.0.0.1:8874"
MAX_BYTES=12_000_000
CACHE_TTL=180
CACHE_LOCK=threading.Lock()
CACHE={"data":None}
PATHS={"/api/global-rf/catalog","/api/ionosphere/snapshot","/api/public-sources/catalog"}
def fetch(path):
    if path not in PATHS:raise ValueError("Unknown feed")
    with urllib.request.urlopen(UPSTREAM+path,timeout=8) as r:
        raw=r.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError("Feed too large")
    return json.loads(raw)
def numeric(v):
    return type(v) in (int,float) and math.isfinite(v)
def coords(lon,lat):
    return numeric(lon) and numeric(lat) and -180<=lon<=180 and -90<=lat<=90
def stamp(value):
    if not isinstance(value,str) or len(value)>40:return None
    try:
        t=dt.datetime.fromisoformat(value.replace("Z","+00:00"))
        return t.astimezone(dt.timezone.utc).isoformat() if t.tzinfo else None
    except ValueError:return None
def clean_catalog(data):
    out=[]
    for f in data.get("features",[])[:5000]:
        try:
            lon,lat=f["geometry"]["coordinates"]
            if not coords(lon,lat):continue
            p=f["properties"]
            scheduled=p.get("scheduled_this_season") is True
            hz=sorted(set(v for v in p.get("frequencies_hz",[])[:256] if numeric(v) and 2e6<=v<=30e6))
            out.append({"lon":lon,"lat":lat,"frequencies_hz":hz[:32],"scheduled_this_season":scheduled})
        except (TypeError,ValueError,KeyError):continue
    return {"status":"ok" if out else "unavailable","source":"HFCC international HF schedule",
            "source_timestamp_utc":stamp(data.get("downloaded_utc")),
            "coverage":"published international HF sites, not complete worldwide transmitter inventory",
            "classification":"scheduled_reference_not_measured_emission","sites":out}
def clean_receivers(data):
    # Aggregate publicly listed receiver coordinates into coarse 1-degree
    # cells; no site IDs, labels, device addresses or individual locations.
    bins={}
    for f in data.get("layers",{}).get("public_sdr_receivers",[])[:10000]:
        try:
            lon,lat=f["geometry"]["coordinates"]
            if not coords(lon,lat):continue
            key=(min(179.5,math.floor(lon)+.5),min(89.5,math.floor(lat)+.5))
            bins[key]=bins.get(key,0)+1
        except (TypeError,ValueError,KeyError):continue
    return {"status":"ok" if bins else "unavailable","source":"Public volunteer SDR directory",
            "source_timestamp_utc":stamp(data.get("generated_at_utc")),
            "classification":"catalog_counts_not_live_reception",
            "cell_size_degrees":1,"cells":[[x,y,n] for (x,y),n in sorted(bins.items())]}
def clean_iono(data):
    out=[]
    for c in data.get("cells",[])[:20000]:
        if not isinstance(c,list) or len(c)!=7 or not all(numeric(v) for v in c):continue
        lon,lat,tec,anomaly,hmf2,fo,flag=c
        if not coords(lon,lat) or not (0<=tec<=500 and -500<=anomaly<=500 and 0<=hmf2<=2000 and 0<=fo<=100):continue
        if flag!=0:continue
        out.append([lon,lat,tec,hmf2,fo])
    return {"status":"ok" if out else "unavailable","source":"NOAA GloTEC",
            "source_timestamp_utc":stamp(data.get("timestamp_utc")),
            "upstream_stale":data.get("stale") is not False,
            "classification":"assimilated_model_not_measured_local_signal",
            "fields":["longitude_deg","latitude_deg","vertical_tec_tecu","hmF2_km","foF2_MHz"],"cells":out}
def refresh():
    previous=CACHE.get("data") or {}
    result={"generated_at_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
            "scope":"global","status":"ok"}
    for key,path,clean in [("radio","/api/global-rf/catalog",clean_catalog),
                           ("ionosphere","/api/ionosphere/snapshot",clean_iono),
                           ("receivers","/api/public-sources/catalog",clean_receivers)]:
        try:
            item=clean(fetch(path))
            if item["status"]!="ok":raise ValueError("empty source")
            result[key]={**item,"cache_stale":False}
        except Exception:
            result[key]={**previous.get(key,{"status":"unavailable"}),"cache_stale":True}
            result["status"]="partial"
    with CACHE_LOCK:CACHE["data"]=result
def background():
    while True:
        refresh()
        time.sleep(CACHE_TTL)
def snapshot():
    with CACHE_LOCK:return CACHE["data"] or {"status":"warming_up","scope":"global"}
def distance_km(a,b,c,d):
    x,y=map(math.radians,(a,c));u=math.radians(c-a);v=math.radians(d-b)
    h=math.sin(u/2)**2+math.cos(x)*math.cos(y)*math.sin(v/2)**2
    return 6371.0088*2*math.asin(math.sqrt(max(0,min(1,h))))
def location(lat,lon):
    if not coords(lon,lat):raise ValueError("Explicit latitude and longitude required")
    data=snapshot()
    sites=data.get("radio",{}).get("sites",[])
    close=sorted(({"distance_km":round(distance_km(lat,lon,s["lat"],s["lon"]),2),
                    "lat":s["lat"],"lon":s["lon"],"frequencies_hz":s["frequencies_hz"],"scheduled_this_season":s["scheduled_this_season"]} for s in sites),
                 key=lambda x:x["distance_km"])[:8]
    cells=data.get("ionosphere",{}).get("cells",[])
    nearest=min(cells,key=lambda c:distance_km(lat,lon,c[1],c[0]),default=None)
    return {"location_basis":"viewer_supplied_coordinates","nearest_public_schedule_sites":close,
            "nearest_ionosphere_model_cell":nearest,
            "classification":"geographic_context_not_reception_prediction"}
class Handler(BaseHTTPRequestHandler):
    server_version="RefraxAPI/1.0"
    sys_version=""
    def log_message(self,*args):pass
    def setup(self):
        self.request.settimeout(6)
        super().setup()
    def send(self,status,data):
        payload=json.dumps(data,separators=(",",":"),allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(payload)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Referrer-Policy","no-referrer")
        self.send_header("Vary","Origin")
        if self.headers.get("Origin")==ORIGIN:
            self.send_header("Access-Control-Allow-Origin",ORIGIN)
        self.end_headers()
        self.wfile.write(payload)
    def path_name(self):
        p=urlsplit(self.path)
        if p.query or p.fragment:return ""
        return p.path.removeprefix("/refrax-api") if p.path.startswith("/refrax-api/") else p.path
    def do_GET(self):
        path=self.path_name()
        if path=="/v1/health":return self.send(200,{"service":"Refrax Observatory API","ok":True})
        if path=="/v1/snapshot":return self.send(200,snapshot())
        self.send(404,{"error":"not found"})
    def do_OPTIONS(self):
        if self.path_name()!="/v1/location" or self.headers.get("Origin")!=ORIGIN:
            return self.send(403,{"error":"not permitted"})
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin",ORIGIN)
        self.send_header("Access-Control-Allow-Methods","POST")
        self.send_header("Access-Control-Allow-Headers","Content-Type")
        self.send_header("Vary","Origin")
        self.end_headers()
    def do_POST(self):
        if self.path_name()!="/v1/location":return self.send(404,{"error":"not found"})
        if self.headers.get("Origin") not in (None,ORIGIN):return self.send(403,{"error":"origin not permitted"})
        try:
            if self.headers.get("Transfer-Encoding"):raise ValueError()
            if self.headers.get_content_type()!="application/json":raise ValueError()
            n=int(self.headers.get("Content-Length","0"))
            if not 0<n<=1024:return self.send(413,{"error":"body size"})
            data=json.loads(self.rfile.read(n))
            if not isinstance(data,dict) or set(data)!={"latitude","longitude"}:raise ValueError()
            result=location(data["latitude"],data["longitude"])
        except (ValueError,TypeError,KeyError,TimeoutError):
            return self.send(400,{"error":"explicit valid coordinates required"})
        self.send(200,result)
class Server(ThreadingHTTPServer):
    daemon_threads=True
    request_queue_size=32
    def __init__(self,*args):
        self.slots=threading.BoundedSemaphore(16)
        super().__init__(*args)
    def process_request(self,request,address):
        if not self.slots.acquire(False):
            self.shutdown_request(request);return
        try:super().process_request(request,address)
        except Exception:self.slots.release();raise
    def process_request_thread(self,*args):
        try:super().process_request_thread(*args)
        finally:self.slots.release()
if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--port",type=int,default=8875)
    args=parser.parse_args()
    threading.Thread(target=background,daemon=True).start()
    Server(("127.0.0.1",args.port),Handler).serve_forever()
