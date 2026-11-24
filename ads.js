"use strict";
// Responsive visible ads load by default; isolate all third-party frames.
(() => {
 const $=id=>document.getElementById(id);
 const sizes={
  "banner-728x90":[728,90],"banner-468x60":[468,60],"banner-320x50":[320,50],
  "banner-300x250":[300,250],"banner-160x300":[160,300],"banner-160x600":[160,600],
  "native":[300,250],"extra-1":[300,300],"extra-2":[300,300]
 };
 let enabled=true,extra=null;
 try{enabled=localStorage.getItem("refrax-ads-disabled")!=="yes"}catch{}
 const slots=["ad-top","ad-rail","ad-rectangle","ad-native","ad-extra"];
 const observer=new IntersectionObserver(entries=>{
  for(const entry of entries){
   const slot=entry.target;
   if(!entry.isIntersecting||!enabled||slot.hidden||!slot.dataset.unit||slot.querySelector("iframe"))continue;
   const unit=slot.dataset.unit;
   const [width,height]=sizes[unit];
   const f=document.createElement("iframe");
   f.title="Third-party advertisement";
   f.width=String(width);f.height=String(height);
   f.setAttribute("sandbox","allow-scripts allow-popups");
   f.setAttribute("allow","geolocation 'none'; camera 'none'; microphone 'none'; payment 'none'");
   f.referrerPolicy="no-referrer";
   f.loading="lazy";
   f.src="ads/"+unit+".html";
   slot.append(f);
  }
 },{threshold:0.15});
 function place(id,unit){
  const slot=$(id);
  if(slot.dataset.unit===String(unit||"")&&slot.hidden===!unit)return;
  observer.unobserve(slot);
  slot.replaceChildren();
  slot.dataset.unit=unit||"";
  slot.hidden=!unit;
  if(unit)observer.observe(slot);
 }
 function layout(){
  $("ads-choice").textContent=enabled?"Hide advertisements":"Show advertisements";
  $("ads-choice").setAttribute("aria-pressed",String(enabled));
  $("sponsors").hidden=!enabled;
  const w=document.documentElement.clientWidth,h=window.innerHeight;
  const top=w>=748?"banner-728x90":w>=488?"banner-468x60":w>=320?"banner-320x50":null;
  const rail=enabled&&w>=1250?(h>=780?"banner-160x600":"banner-160x300"):null;
  document.body.classList.toggle("ads-rail",Boolean(rail));
  place("ad-top",enabled?top:null);
  place("ad-rail",rail);
  place("ad-rectangle",enabled&&w>=344?"banner-300x250":null);
  place("ad-native",enabled&&w>=344?"native":null);
  place("ad-extra",enabled&&w>=344?extra:null);
  requestAnimationFrame(()=>window.dispatchEvent(new Event("refrax:layout-change")));
 }
 $("ads-choice").addEventListener("click",()=>{
  enabled=!enabled;
  if(!enabled)extra=null;
  try{localStorage.setItem("refrax-ads-disabled",enabled?"no":"yes")}catch{}
  layout();
 });
 for(const b of document.querySelectorAll("[data-ad-extra]"))b.addEventListener("click",()=>{extra=b.dataset.adExtra;layout()});
 $("ad-extra-close").addEventListener("click",()=>{extra=null;layout()});
 let timer;
 window.addEventListener("resize",()=>{clearTimeout(timer);timer=setTimeout(layout,180)});
 layout();
})();
