"""Local user-controlled OpenAI-compatible observatory assistant.
Run only on your own computer. No model or shell execution on the data server.
"""
import argparse,json,urllib.request
from urllib.parse import urlsplit
API="https://en-route.ringtail-anoles.ts.net/refrax-api/v1"
def request(url,body=None):
    data=None if body is None else json.dumps(body).encode()
    req=urllib.request.Request(url,data=data,headers={"Content-Type":"application/json"} if data else {})
    with urllib.request.urlopen(req,timeout=90) as r:
        raw=r.read(5_000_001)
    if len(raw)>5_000_000:raise ValueError("Response too large")
    return json.loads(raw)
def context(api,lat=None,lon=None):
    d=request(api.rstrip("/")+"/snapshot")
    radio=d.get("radio",{});iono=d.get("ionosphere",{})
    result={"status":d.get("status"),"scope":"global","radio":{"site_count":len(radio.get("sites",[])),"classification":radio.get("classification"),"source_timestamp_utc":radio.get("source_timestamp_utc")},"ionosphere":{"cell_count":len(iono.get("cells",[])),"source_timestamp_utc":iono.get("source_timestamp_utc"),"classification":iono.get("classification"),"stale":iono.get("upstream_stale") or iono.get("cache_stale")}}
    if (lat is None)!=(lon is None):raise ValueError("Both coordinates are required")
    if lat is not None:
        result["location_context"]=request(api.rstrip("/")+"/location",{"latitude":lat,"longitude":lon})
    return result
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--api",default=API)
    p.add_argument("--model-url",default="http://127.0.0.1:11434/v1")
    p.add_argument("--model",required=True)
    p.add_argument("--lat",type=float)
    p.add_argument("--lon",type=float)
    p.add_argument("question")
    a=p.parse_args()
    u=urlsplit(a.model_url)
    if u.scheme!="http" or u.hostname not in ("127.0.0.1","localhost","::1") or u.username or u.password:
        p.error("Model endpoint must be your loopback HTTP server")
    data=context(a.api,a.lat,a.lon)
    response=request(a.model_url.rstrip("/")+"/chat/completions",{"model":a.model,"messages":[{"role":"system","content":"Interpret public scientific model context. Separate modeled estimates from measurements; do not invent observations or assert source identity. No executable tools."},{"role":"user","content":a.question+"\nData context:\n"+json.dumps(data)}],"temperature":.2,"stream":False})
    print(response["choices"][0]["message"]["content"])
if __name__=="__main__":main()
