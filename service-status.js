"use strict";
(() => {
 const node=document.getElementById("live-service-status");
 const endpoint="https://en-route.ringtail-anoles.ts.net/refrax-api/v1/health";
 let busy=false;
 async function check(){
  if(busy||document.hidden)return;busy=true;
  try{
   const response=await fetch(endpoint,{cache:"no-store",credentials:"omit",signal:AbortSignal.timeout(8000),referrerPolicy:"no-referrer"});
   if(!response.ok)throw Error("HTTP "+response.status);
   const data=await response.json();
   const online=data.observatory_online===true;
   const known=typeof data.observatory_online==="boolean";
   node.textContent=online?"Observatory online":known?"Observatory unavailable":"Gateway online · checking core";
   node.dataset.state=online?"online":known?"offline":"unknown";
   node.title="Server health, independent of agent connectivity and scientific feed freshness.";
  }catch{node.textContent="Browser cannot reach API";node.dataset.state="unknown";node.title="The browser could not reach the endpoint; this is not proof that the server is stopped. Try the Full-screen observatory link. A tailnet browser may require its own local-network permission.";}
  finally{busy=false;}
 }
 check();setInterval(check,30000);document.addEventListener("visibilitychange",check);
})();