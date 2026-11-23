import json
import math
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch
import api
import agent

class PublicGateway(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cat={"downloaded_utc":"2026-11-23T12:00:00Z","features":[
            {"geometry":{"coordinates":[0,0]},"properties":{"scheduled_this_season":True,"frequencies_hz":[1,5e6,10e6,float("nan")],"private_id":"DO_NOT_EXPORT"}},
            {"geometry":{"coordinates":[999,0]},"properties":{"scheduled_this_season":True,"frequencies_hz":[5e6]}}]}
        ion={"timestamp_utc":"2026-11-23T12:00:00Z","stale":False,"cells":[[0,0,10,0,300,5,0],[1,1,20,0,300,5,1]]}
        cls.data={"status":"ok","scope":"global","radio":api.clean_catalog(cat),"ionosphere":api.clean_iono(ion)}
        api.CACHE["data"]=cls.data
        cls.server=api.Server(("127.0.0.1",0),api.Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.url="http://127.0.0.1:"+str(cls.server.server_port)
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()
    def call(self,path,body=None,origin=None):
        headers={}
        if origin:headers["Origin"]=origin
        if body is not None:headers["Content-Type"]="application/json"
        req=urllib.request.Request(self.url+path,headers=headers,data=None if body is None else json.dumps(body).encode())
        try:r=urllib.request.urlopen(req,timeout=3)
        except urllib.error.HTTPError as e:r=e
        with r:return r.code,json.load(r),dict(r.headers)
    def test_public_schema(self):
        code,data,headers=self.call("/v1/snapshot",origin=api.ORIGIN)
        self.assertEqual(code,200);self.assertEqual(data["scope"],"global")
        self.assertNotIn("DO_NOT_EXPORT",json.dumps(data))
        self.assertEqual(len(data["radio"]["sites"]),1)
        self.assertEqual(len(data["ionosphere"]["cells"]),1)
        self.assertEqual(headers["Access-Control-Allow-Origin"],api.ORIGIN)
    def test_unknown_routes(self):
        for p in ["/api/orchestrator/devices","/api/health","/api/observations/detail","/v1/snapshot?url=http://localhost","/refrax-api/../api/health","/api/sonification/catalog","/v1/location","/api/motion/aircraft"]:
            self.assertEqual(self.call(p)[0],404,p)
    def test_no_location_fallback(self):
        for body in ({},{ "latitude":None,"longitude":0},{"latitude":91,"longitude":0},{"latitude":True,"longitude":0},{"latitude":0,"longitude":0,"owner":True}):
            self.assertEqual(self.call("/v1/location",body)[0],400)
        before=json.dumps(api.snapshot(),sort_keys=True)
        a=self.call("/v1/location",{"latitude":0,"longitude":0})[1]
        b=self.call("/refrax-api/v1/location",{"latitude":45,"longitude":45})[1]
        self.assertEqual(a["nearest_public_schedule_sites"][0]["distance_km"],0)
        self.assertGreater(b["nearest_public_schedule_sites"][0]["distance_km"],1000)
        self.assertEqual(json.dumps(api.snapshot(),sort_keys=True),before)
    def test_origin(self):
        self.assertEqual(self.call("/v1/location",{"latitude":0,"longitude":0},"https://invalid.example")[0],403)
        self.assertNotIn("Access-Control-Allow-Origin",self.call("/v1/snapshot",origin="https://invalid.example")[2])
    def test_agent_context(self):
        a=agent.context(self.url+"/v1")
        self.assertEqual(a["radio"]["site_count"],1)
        self.assertNotIn("location_context",a)
        b=agent.context(self.url+"/v1",0,0)
        self.assertIn("location_context",b)
        with self.assertRaises(ValueError):agent.context(self.url+"/v1",0,None)
    def test_stale_and_bounds(self):
        self.assertAlmostEqual(api.distance_km(0,0,0,180),math.pi*6371.0088)
        with patch.object(api,"fetch",side_effect=ConnectionError("secret upstream error")):
            api.refresh()
            data=api.snapshot()
            self.assertTrue(data["radio"]["cache_stale"])
            self.assertNotIn("secret upstream error",json.dumps(data))
        api.CACHE["data"]=self.data
if __name__=="__main__":unittest.main()
