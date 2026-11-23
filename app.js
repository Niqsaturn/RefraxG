"use strict";
const API="https://en-route.ringtail-anoles.ts.net/refrax-api/v1";
const $=id=>document.getElementById(id);
let map, selected=null, placing=false, snapshot=null;
const empty=()=>({type:"FeatureCollection",features:[]});
const point=(lon,lat,properties)=>({type:"Feature",geometry:{type:"Point",coordinates:[lon,lat]},properties});
function setStatus(s){$("status").textContent=s}
function request(path,options={}){return fetch(API+path,{...options,credentials:"omit",cache:"no-store",referrerPolicy:"no-referrer",signal:AbortSignal.timeout(12000)}).then(r=>{if(!r.ok)throw Error("API "+r.status);return r.json()})}
function project(lon,lat,r,b){
 const rad=Math.PI/180,phi=lat*rad,delta=r/6371008.8;
 const q=Math.asin(Math.min(1,Math.max(-1,Math.sin(phi)*Math.cos(delta)+Math.cos(phi)*Math.sin(delta)*Math.cos(b))));
 const x=lon*rad+Math.atan2(Math.sin(b)*Math.sin(delta)*Math.cos(phi),Math.cos(delta)-Math.sin(phi)*Math.sin(q));
 return [((x/rad+540)%360)-180,q/rad]
}
function rings(lon,lat){
 const f=Number($("freq").value)*1e6;
 if(!Number.isFinite(f)||f<2e6||f>30e9||Math.abs(lat)>84){setStatus("Use a valid frequency and nonpolar map location.");return}
 const lambda=299792458/f,guard=Math.max(20,3*lambda),features=[];
 // Explicit geometric 1 W isotropic scenario. Rings have real meter radii;
 // their vertical display height is a schematic visualization, not field height.
 for(const r of [100,300,1000,3000,10000]){
  if(r<guard)continue;
  const outer=[],inner=[],width=Math.max(2,r*.012);
  for(let i=0;i<=96;i++){const b=i*2*Math.PI/96;outer.push(project(lon,lat,r+width,b));inner.push(project(lon,lat,r,b))}
  if(outer.some((p,i)=>i&&Math.abs(p[0]-outer[i-1][0])>180))continue;
  features.push({type:"Feature",geometry:{type:"Polygon",coordinates:[outer,inner.reverse()]},properties:{r,displayHeight:Math.max(8,r*.025),flux:1/(4*Math.PI*r*r)}})
 }
 map.getSource("wave").setData({type:"FeatureCollection",features});
 $("physics").textContent="Wavelength: "+lambda.toPrecision(5)+" m. S=P/(4πr²), E_rms=√(376.73 S). Range guard: "+guard.toFixed(1)+" m. Ring height is illustrative.";
 setStatus("Conditional reference wave at selected point; not a detected transmitter.")
}
function applySnapshot(data){
 snapshot=data;
 const sites=data.radio?.sites||[],cells=data.ionosphere?.cells||[],receivers=data.receivers?.cells||[];
 map.getSource("radio").setData({type:"FeatureCollection",features:sites.map(s=>point(s.lon,s.lat,{frequencies:s.frequencies_hz.join(", "),scheduled:s.scheduled_this_season===true}))});
 map.getSource("iono").setData({type:"FeatureCollection",features:cells.map(c=>point(c[0],c[1],{tec:c[2]}))});
 map.getSource("receivers").setData({type:"FeatureCollection",features:receivers.map(c=>point(c[0],c[1],{count:c[2]}))});
 $("health").textContent=data.status==="ok"?"Global feed available":"Partial / delayed feed";
 setStatus(sites.length+" HF reference sites · "+receivers.length+" receiver-density cells · "+cells.length+" quality-qualified global model cells. Source time: "+(data.ionosphere?.source_timestamp_utc||"unavailable")+(data.ionosphere?.cache_stale||data.ionosphere?.upstream_stale?" (stale)":""));
}
async function load(){try{applySnapshot(await request("/snapshot"))}catch(e){$("health").textContent="API unavailable";setStatus("Global feed unavailable. Manual wave scenarios remain usable.")}}
function init(){
 if(!window.maplibregl){setStatus("Map renderer unavailable.");return}
 map=new maplibregl.Map({container:"map",style:"https://tiles.openfreemap.org/styles/liberty",center:[0,15],zoom:1.4,pitch:0,maxPitch:75,attributionControl:true});
 map.addControl(new maplibregl.NavigationControl(),"top-right");
 map.on("load",()=>{
  const layers=map.getStyle().layers;
  const b=layers.find(l=>l["source-layer"]==="building");
  if(b&&!layers.some(l=>l.type==="fill-extrusion"&&l["source-layer"]==="building")){
   map.addLayer({id:"city-buildings",source:b.source,"source-layer":"building",type:"fill-extrusion",minzoom:14,
    filter:["has","render_height"],paint:{"fill-extrusion-color":"#829aa4","fill-extrusion-height":["to-number",["get","render_height"],0],"fill-extrusion-base":["to-number",["get","render_min_height"],0],"fill-extrusion-opacity":.8}});
  }
  for(const id of ["radio","iono","wave","receivers"])map.addSource(id,{type:"geojson",data:empty()});
  map.addLayer({id:"radio-layer",type:"circle",source:"radio",paint:{"circle-radius":4,"circle-color":["case",["get","scheduled"],"#f5b66c","#7d95a2"],"circle-stroke-width":1,"circle-stroke-color":"#182b35"}});
  map.addLayer({id:"receivers-layer",type:"circle",source:"receivers",paint:{"circle-radius":["interpolate",["linear"],["get","count"],1,3,20,12],"circle-color":"#70ded2","circle-opacity":.6}});
  map.addLayer({id:"iono-layer",type:"circle",source:"iono",layout:{visibility:"none"},paint:{"circle-radius":["interpolate",["linear"],["zoom"],1,2,5,8],"circle-opacity":.65,"circle-color":["interpolate",["linear"],["get","tec"],0,"#426ab1",30,"#4dd8b7",100,"#f0aa56"]}});
  map.addLayer({id:"wave-layer",type:"fill-extrusion",source:"wave",paint:{"fill-extrusion-color":"#35d9ce","fill-extrusion-height":["get","displayHeight"],"fill-extrusion-opacity":.45}});
  map.on("click",e=>{selected={latitude:e.lngLat.lat,longitude:e.lngLat.lng};if(placing){placing=false;rings(selected.longitude,selected.latitude)}else setStatus("Map location selected. Request context if desired.")});
  $("globe").onclick=()=>map.easeTo({center:[0,15],zoom:1.4,pitch:0,bearing:0});
  $("city").onclick=()=>map.easeTo({pitch:map.getPitch()>10?0:58,bearing:map.getPitch()>10?0:25});
  $("wave").onclick=()=>{placing=true;setStatus("Click the map to place a hypothetical source.")};
  $("clear").onclick=()=>{map.getSource("wave").setData(empty());placing=false};
  for(const id of ["radio","iono","receivers"])$(id).onchange=()=>map.setLayoutProperty(id+"-layer","visibility",$(id).checked?"visible":"none");
  $("locate").onclick=()=>{
   if(!navigator.geolocation){setStatus("Browser location unavailable; select a point manually.");return}
   navigator.geolocation.getCurrentPosition(p=>{selected={latitude:p.coords.latitude,longitude:p.coords.longitude};map.easeTo({center:[selected.longitude,selected.latitude],zoom:14});setStatus("Location centered locally. No coordinates sent to the observatory.")},()=>setStatus("Location permission unavailable; select a map point."),{enableHighAccuracy:false,maximumAge:60000,timeout:10000})
  };
  $("context").onclick=async()=>{
   if(!selected){$("result").textContent="Select a point or use browser location first.";return}
   try{$("result").textContent=JSON.stringify(await request("/location",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(selected)}),null,2)}catch(e){$("result").textContent="Location lookup unavailable."}
  };
  load();setInterval(()=>{if(!document.hidden)load()},180000)
 });
}
init();
