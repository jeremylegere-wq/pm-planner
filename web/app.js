"use strict";
/* PM Planner front-end – vanilla JS, no external dependencies (works offline / on locked-down networks). */

const STATUS_COLOR = {Unplanned:"#9a9892",Proposed:"#2a78d6",Offered:"#eb6834",Confirmed:"#1baf7a",
  Reschedule:"#eda100",Declined:"#e34948",Completed:"#6250d6",Closed:"#bdbbb5"};
const LIGHT_TEXT = new Set(["Reschedule"]);
const $ = (s, r=document) => r.querySelector(s);
const $$ = (s, r=document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const S = {boot:null, orders:[], dash:null, df:{region:null, account:null}, mapMode:"mix", view:"dash", sel:new Set(), selected:null,
  g:{start:null, days:14, px:100, status:new Set(["Proposed","Offered","Confirmed","Reschedule"]), mod:"", region:""},
  bl:{mod:"", region:"", q:"", due:""}, wf:{q:"", status:"", mod:"", region:"", action:false},
  letter:{key:"booking_request", wos:[], previews:[], skip:new Set()}};

async function api(path, body, method) {
  const r = await fetch("/api/" + path, body !== undefined ? {method: method || "POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)} : {});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
function toast(msg, ms=3200) { const t=$("#toast"); t.textContent=msg; t.style.display="block"; clearTimeout(t._h); t._h=setTimeout(()=>t.style.display="none", ms); }
const iso = d => { const z=new Date(d.getTime()-d.getTimezoneOffset()*60000); return z.toISOString().slice(0,10); };
const parseD = s => { const [y,m,d]=s.slice(0,10).split("-").map(Number); return new Date(y,m-1,d); };
const addDays = (d,n) => { const x=new Date(d); x.setDate(x.getDate()+n); return x; };
const fmtD = s => s ? parseD(s).toLocaleDateString("en-AU",{day:"2-digit",month:"short",year:"numeric"}) : "–";
const fmtDT = s => { if(!s) return "–"; const d=new Date(s); return d.toLocaleDateString("en-AU",{weekday:"short",day:"2-digit",month:"short"})+" "+d.toTimeString().slice(0,5); };
const engName = id => (S.boot.engineers.find(e=>e.id===id)||{}).name || "–";
const chip = st => `<span class="chip ${LIGHT_TEXT.has(st)?"light":""}" style="--c:${STATUS_COLOR[st]||"#999"}">${esc(st)}</span>`;

/* ------------------------------------------------------------------ boot & nav */
async function init() {
  S.boot = await api("bootstrap");
  $("#coName").textContent = S.boot.company.name;
  const t = parseD(S.boot.today); S.g.start = addDays(t, -((t.getDay()+6)%7)); // Monday this week
  await reloadAll();
  $$("#nav button").forEach(b => b.onclick = () => go(b.dataset.v));
  $("#btnRefresh").onclick = doRefresh;
  document.addEventListener("mousemove", tipMove);
  go("dash");
}
function loadDash() { const q=new URLSearchParams(); if(S.df.region) q.set("region",S.df.region); if(S.df.account) q.set("account",S.df.account); return api("dashboard?"+q); }
async function setFilter(f) { S.df={region:null, account:null, ...f}; S.dash=await loadDash(); renderDash(); }
async function reloadAll() {
  [S.orders, S.dash] = await Promise.all([api("orders"), loadDash()]);
  const lr = S.dash.last_refresh;
  $("#refreshInfo").textContent = "Report refreshed " + (lr ? new Date(lr).toLocaleString("en-AU",{day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit"}) : "–");
}
function go(v) {
  S.view = v;
  $$("#nav button").forEach(b => b.classList.toggle("on", b.dataset.v===v));
  $$(".view").forEach(s => s.classList.toggle("on", s.id==="v-"+v));
  closeDrawer();
  $('#pageTitle').textContent={dash:'Planned maintenance overview',plan:'Planner',wos:'Work orders',letters:'Correspondence',data:'Data & export'}[v];
  ({dash:renderDash, plan:renderPlan, wos:renderWos, letters:renderLetters, data:renderData})[v]();
}
async function refreshView() { await reloadAll(); go(S.view); }
async function doRefresh() {
  try { const r = await api("refresh", {}); toast(`Report refreshed: ${r.added} new, ${r.updated} updated, ${r.removed} no longer open`); await refreshView(); }
  catch(e) { toast("Refresh failed: " + e.message, 6000); }
}

/* ------------------------------------------------------------------ tooltip */
function tipMove(e) {
  const t = e.target.closest && e.target.closest("[data-tip]"); const tip = $("#tip");
  if (!t) { tip.style.display="none"; return; }
  tip.innerHTML = t.dataset.tip; tip.style.display="block";
  tip.style.left = Math.min(e.clientX+14, innerWidth-300)+"px"; tip.style.top = (e.clientY+14)+"px";
}

/* ------------------------------------------------------------------ dashboard */
function kpi(n, label, sub, color, onclick) {
  return `<div class="kpi" style="--c:${color}" data-go='${onclick}'><div class="n">${n}</div><div class="l">${label}</div><div class="sub">${sub||"&nbsp;"}</div></div>`;
}
function renderDash() {
  const d = S.dash, k = d.kpis;
  const waiting = k.offered + k.reschedule;
  $("#v-dash").innerHTML = `
  <div class="toprow">
    <div class="card mapcard">
      <div class="maphead"><div><div class="chart-title">Where the work is</div><div class="chart-sub">Each bubble is a customer site · size = open PM work orders · click to cross-filter the dashboard</div></div>
        <div class="seg" id="mapMode"><button data-m="mix" class="${S.mapMode==="mix"?"on":""}">Status mix</button><button data-m="attn" class="${S.mapMode==="attn"?"on":""}">Needs attention</button></div></div>
      <div class="chips" id="mapChips"></div>
      <div class="maps"><svg id="mState" viewBox="0 0 ${MAP.sw} ${MAP.sh}"></svg><svg id="mMetro" viewBox="0 0 ${MAP.mw} ${MAP.mh}"></svg></div>
      <div class="legend" id="mapLegend"></div>
    </div>
    <div class="kpigrid">
      ${kpi(k.open,"Open PM work orders",S.df.account||S.df.region||"all of Victoria",  "#4b5163", "wos|")}
      ${kpi(k.unplanned,"Unplanned","need a date","#9a9892","wos|Unplanned")}
      ${kpi(k.proposed,"Ready to offer","on the calendar, not sent","#2a78d6","wos|Proposed")}
      ${kpi(waiting,"Awaiting customer","offered / rescheduling","#eb6834","wos|Offered")}
      ${kpi(k.confirmed,"Confirmed","booked in","#1baf7a","wos|Confirmed")}
      ${kpi(k.overdue,"Overdue","past PM due date, not confirmed","#e34948","wos|overdue")}
      ${kpi(k.confirm_rate+"%","Confirmation rate","of offers sent","#6250d6","wos|")}
      <div class="kpi selcard" style="--c:#7fb2ff;cursor:default" id="selCard"></div>
    </div>
  </div>
  <div class="grid cols-2" style="margin-bottom:14px">
    <div class="card"><div class="chart-title">PM workload by month due</div><div class="chart-sub">Work orders by planning status – where the pipeline is stuck</div><div id="cMonths"></div></div>
    <div class="card"><div class="chart-title">Offers awaiting a reply</div><div class="chart-sub">Business days since the last letter · ${S.boot.company.name} hold is 5 business days</div><div id="cAgeing"></div>
      <div class="chart-title" style="margin-top:14px">Category mix (open)</div><div id="cMod"></div></div>
  </div>
  <div class="grid cols-2" style="margin-bottom:14px">
    <div class="card"><div class="chart-title">Technician utilisation – next 4 weeks</div><div class="chart-sub">Booked hours ÷ available hours (excludes weekends, holidays and leave)</div><div id="cUtil"></div></div>
    <div class="card"><div class="chart-title">Status by service territory</div><div class="chart-sub">Open work orders</div><div id="cRegion"></div></div>
  </div>
  <div class="grid cols-2">
    <div class="card"><h2>Action queue <span class="muted small">· ${d.action_total} customer actions, most urgent first</span></h2><div class="scroll" style="max-height:420px"><table class="t" id="tQueue"></table></div></div>
    <div class="card"><h2>Next 14 days on site</h2><div class="scroll" style="max-height:420px"><table class="t" id="tUpcoming"></table></div></div>
  </div>`;
  $$(".kpi").forEach(el => el.onclick = () => { const [v, f]=el.dataset.go.split("|"); S.wf={q:S.df.account||"",status:"",mod:"",region:S.df.region||"",action:false,overdue:false}; if(f==="overdue") S.wf.overdue=true; else S.wf.status=f; go(v); });
  drawMaps();
  const keys = ["Unplanned","Proposed","Offered","Confirmed","Completed","Declined"];
  $("#cMonths").innerHTML = stackedColumns(d.months, keys) + legend(keys);
  $("#cAgeing").innerHTML = hbars(Object.entries(d.ageing).map(([l,v])=>({label:l,value:v})), STATUS_COLOR.Offered, v=>v+" offers");
  $("#cMod").innerHTML = hbars(Object.entries(d.category).sort((a,b)=>b[1]-a[1]).map(([l,v])=>({label:l,value:v})), "#2a78d6", v=>v+" work orders");
  $("#cUtil").innerHTML = hbars(d.utilisation.map(u=>({label:u.name,value:u.pct,sub:`${u.booked}h of ${u.available}h · ${u.home}`})), "#2a78d6", v=>v+"%", 100);
  const rk = ["Unplanned","Proposed","Offered","Confirmed","Reschedule"];
  $("#cRegion").innerHTML = stackedH(Object.entries(d.region).map(([l,v])=>({label:l,segs:v})), rk) + legend(rk);
  $("#tQueue").innerHTML = `<tr><th>Customer</th><th>Next step</th><th>WOs</th><th>Earliest due</th><th></th></tr>` +
    d.actions.map((a,i)=>`<tr><td>${esc(a.account)}</td><td>${esc(a.label)}</td><td>${a.wos.length}</td><td>${fmtD(a.earliest_due)}</td>
      <td>${a.letter ? `<button class="btn sm" data-q="${i}">Prepare letter</button>` : `<button class="btn ghost sm" data-p="${i}">Open</button>`}</td></tr>`).join("") || `<tr><td class="empty">Nothing waiting</td></tr>`;
  $$("#tQueue [data-q]").forEach(b => b.onclick = () => { const a=d.actions[b.dataset.q]; openLetters(a.letter, a.wos); });
  $$("#tQueue [data-p]").forEach(b => b.onclick = () => { const a=d.actions[b.dataset.p]; S.wf={q:a.account,status:"",mod:"",region:"",action:false}; go(a.action==="plan_urgent"?"plan":"wos"); });
  $("#tUpcoming").innerHTML = `<tr><th>When</th><th>Customer</th><th>Type</th><th>Technician</th><th>Status</th></tr>` +
    d.upcoming.map(u=>`<tr><td>${fmtDT(u.start)}</td><td>${esc(u.account)}</td><td>${u.category}</td><td>${esc(u.engineer)}</td><td>${chip(u.status)}</td></tr>`).join("");
}
function legend(keys) { return `<div class="legend">${keys.map(k=>`<span><i style="background:${STATUS_COLOR[k]}"></i>${k}</span>`).join("")}</div>`; }
function stackedColumns(rows, keys) {
  const W=640,H=250,L=34,B=28,T=8, max=Math.max(1,...rows.map(r=>keys.reduce((s,k)=>s+(r[k]||0),0)))*1.12;
  const bw=Math.min(54,(W-L)/rows.length*0.62), step=(W-L)/rows.length;
  let g=""; const ticks=4;
  for(let i=0;i<=ticks;i++){const v=Math.round(max*i/ticks), y=T+(H-T-B)*(1-i/ticks); g+=`<line x1="${L}" x2="${W}" y1="${y}" y2="${y}" stroke="#e6eaf0"/><text x="${L-6}" y="${y+4}" text-anchor="end">${v}</text>`;}
  rows.forEach((r,i)=>{
    const x=L+step*i+(step-bw)/2; let y=H-B; const tot=keys.reduce((s,k)=>s+(r[k]||0),0);
    const lab=new Date(r.month+"-01").toLocaleDateString("en-AU",{month:"short",year:"numeric"});
    keys.forEach(k=>{const v=r[k]||0; if(!v) return; const h=(H-T-B)*v/max; y-=h;
      g+=`<rect x="${x}" y="${y+1}" width="${bw}" height="${Math.max(h-2,1)}" rx="2" fill="${STATUS_COLOR[k]}" data-tip="<b>${lab}</b><br>${k}: ${v}"/>`;});
    g+=`<text x="${x+bw/2}" y="${y-4}" text-anchor="middle" style="font-weight:600;fill:#222">${tot}</text><text x="${x+bw/2}" y="${H-10}" text-anchor="middle">${lab}</text>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" width="100%">${g}</svg>`;
}
function hbars(rows, color, fmt, maxv) {
  const max = maxv || Math.max(1,...rows.map(r=>r.value)), rh = 26, W=640, L=150;
  let g=""; rows.forEach((r,i)=>{ const y=i*rh+4, w=(W-L-70)*Math.min(r.value,max)/max;
    g+=`<text x="${L-8}" y="${y+14}" text-anchor="end">${esc(r.label)}</text><rect x="${L}" y="${y+2}" width="${Math.max(w,2)}" height="16" rx="3" fill="${color}" data-tip="<b>${esc(r.label)}</b><br>${fmt(r.value)}${r.sub?"<br>"+esc(r.sub):""}"/>
        <text x="${L+Math.max(w,2)+6}" y="${y+14}" style="font-weight:600;fill:#222">${fmt(r.value).split(" ")[0]}</text>`;});
  return `<svg viewBox="0 0 ${W} ${rows.length*rh+8}" width="100%">${g}</svg>`;
}
function stackedH(rows, keys) {
  const rh=32,W=640,L=110; const max=Math.max(1,...rows.map(r=>keys.reduce((s,k)=>s+(r.segs[k]||0),0)));
  let g=""; rows.forEach((r,i)=>{ const y=i*rh+4; let x=L; const tot=keys.reduce((s,k)=>s+(r.segs[k]||0),0);
    g+=`<text x="${L-8}" y="${y+16}" text-anchor="end">${esc(r.label)}</text>`;
    keys.forEach(k=>{const v=r.segs[k]||0; if(!v) return; const w=(W-L-50)*v/max; g+=`<rect x="${x+1}" y="${y+3}" width="${Math.max(w-2,1)}" height="20" rx="2" fill="${STATUS_COLOR[k]}" data-tip="<b>${esc(r.label)}</b><br>${k}: ${v}"/>`; x+=w;});
    g+=`<text x="${x+6}" y="${y+17}" style="font-weight:600;fill:#222">${tot}</text>`;});
  return `<svg viewBox="0 0 ${W} ${rows.length*rh+8}" width="100%">${g}</svg>`;
}


/* ------------------------------------------------------------------ interactive map (pure SVG, works offline) */
// Approximate outline of Victoria and Port Phillip Bay as [lon, lat]. Good enough for a dashboard backdrop.
const VIC=[[141.0,-34.02],[142.15,-34.18],[143.55,-35.34],[144.75,-36.13],[146.0,-36.0],[146.92,-36.08],[147.9,-36.2],[148.16,-36.05],[149.98,-37.5],[148.9,-37.78],[148.0,-37.88],[147.3,-38.3],[146.65,-38.7],[146.4,-39.1],[146.2,-38.85],[145.97,-38.9],[145.5,-38.67],[145.2,-38.5],[144.89,-38.5],[144.7,-38.4],[144.66,-38.32],[144.52,-38.27],[144.33,-38.33],[143.97,-38.54],[143.5,-38.86],[143.1,-38.7],[142.48,-38.4],[141.6,-38.35],[141.0,-38.07]];
const BAY=[[144.67,-38.27],[144.41,-38.12],[144.5,-37.98],[144.66,-37.9],[144.89,-37.86],[144.95,-37.84],[144.97,-37.87],[145.0,-37.92],[145.07,-38.0],[145.12,-38.14],[145.04,-38.22],[144.74,-38.33]];
const TOWNS=[["Melbourne",-37.81,144.96,"m"],["Geelong",-38.15,144.36],["Ballarat",-37.56,143.85],["Bendigo",-36.76,144.28],["Wodonga",-36.12,146.89],["Sale",-38.11,147.07],["Warrnambool",-38.38,142.48],["Mildura",-34.19,142.16],["Horsham",-36.71,142.2],["Shepparton",-36.38,145.4],["Traralgon",-38.2,146.54],["Wonthaggi",-38.6,145.6]];
const COS=Math.cos(37.5*Math.PI/180);
const MAP={sw:520,sh:375,mw:380,mh:395,
  st:{lon0:140.85,lat0:-33.95,k:70}, mt:{lon0:144.55,lat0:-37.55,k:560}};
const projS=(lat,lon)=>[(lon-MAP.st.lon0)*COS*MAP.st.k,(MAP.st.lat0-lat)*MAP.st.k];
const projM=(lat,lon)=>[(lon-MAP.mt.lon0)*COS*MAP.mt.k,(MAP.mt.lat0-lat)*MAP.mt.k];
const OPENS=["Unplanned","Proposed","Offered","Reschedule","Confirmed"];
function sites() {
  const today=S.boot.today, m=new Map();
  S.orders.filter(o=>OPENS.includes(o.plan_status)&&o.lat!=null).forEach(o=>{
    let s=m.get(o.account); if(!s){ s={account:o.account,region:o.region,lat:o.lat,lon:o.lon,n:0,by:{},overdue:0,action:0}; m.set(o.account,s); }
    s.n++; s.by[o.plan_status]=(s.by[o.plan_status]||0)+1;
    if(o.pm_due<today && o.plan_status!=="Confirmed") s.overdue++; if(o.suggest) s.action++; });
  return [...m.values()];
}
const polyPath=(pts,pr)=>"M"+pts.map(p=>pr(p[1],p[0]).map(v=>v.toFixed(1)).join(",")).join("L")+"Z";
function pieSvg(x,y,r,segs,attrs) {
  const tot=segs.reduce((a,s)=>a+s.v,0); if(!tot) return "";
  const live=segs.filter(s=>s.v>0);
  if(live.length===1) return `<circle cx="${x}" cy="${y}" r="${r}" fill="${live[0].c}" ${attrs}/>`;
  let a=-Math.PI/2, out="";
  live.forEach(s=>{ const b=a+2*Math.PI*s.v/tot, large=b-a>Math.PI?1:0;
    out+=`<path d="M${x},${y}L${x+r*Math.cos(a)},${y+r*Math.sin(a)}A${r},${r} 0 ${large} 1 ${x+r*Math.cos(b)},${y+r*Math.sin(b)}Z" fill="${s.c}"/>`; a=b; });
  return `<g ${attrs}>${out}<circle cx="${x}" cy="${y}" r="${r}" fill="none" stroke="#fff" stroke-width="1.5"/></g>`;
}
function siteSegs(s) {
  if(S.mapMode==="attn") { const od=s.overdue, ac=Math.max(0,Math.min(s.action,s.n)-od), good=Math.max(0,s.n-od-ac);
    return [{v:od,c:"#e34948"},{v:ac,c:"#eb6834"},{v:good,c:"#1baf7a"}]; }
  return OPENS.map(k=>({v:s.by[k]||0,c:STATUS_COLOR[k]}));
}
function siteTip(s) {
  return `<b>${esc(s.account)}</b><br>${s.region} · ${s.n} open work orders<br>`+OPENS.filter(k=>s.by[k]).map(k=>`${k}: ${s.by[k]}`).join(" · ")+(s.overdue?`<br><b>${s.overdue} overdue</b>`:"")+(s.action?`<br>${s.action} need action`:"");
}
function drawMaps() {
  const ss=sites(), f=S.df, W=MAP;
  const dim = s => (f.account&&s.account!==f.account)||(f.region&&s.region!==f.region);
  const rad = (s,k) => k*(5+Math.sqrt(s.n)*2.2);
  // ---- state map
  let g=`<rect width="${W.sw}" height="${W.sh}" rx="8" fill="#e6edf5"/><path d="${polyPath(VIC,projS)}" fill="#f8f8fa" stroke="#b7c3d1" stroke-width="1.2"/><path d="${polyPath(BAY,projS)}" fill="#e6edf5" stroke="#b7c3d1" stroke-width=".8"/>`;
  const mA=projS(-37.55,144.55), mB=projS(-38.25,145.4);
  g+=`<rect x="${mA[0]}" y="${mA[1]}" width="${mB[0]-mA[0]}" height="${mB[1]-mA[1]}" fill="none" stroke="#632ca6" stroke-dasharray="3 3" opacity=".55" rx="3"/>`;
  g+=TOWNS.filter(t=>t[3]!=="m").map(t=>{const [x,y]=projS(t[1],t[2]); return `<circle cx="${x}" cy="${y}" r="1.6" fill="#9aa7b8"/><text x="${x+5}" y="${y+3}" style="font-size:9px;fill:#8a96a6">${t[0]}</text>`;}).join("");
  g+=`<text x="${mB[0]+2}" y="${mB[1]+12}" text-anchor="end" style="font-size:9px;fill:#632ca6;font-weight:600">Metro inset ↗</text>`;
  const inMetro = s => s.lon>=144.55&&s.lon<=145.4&&s.lat<=-37.55&&s.lat>=-38.25;
  const outside = ss.filter(s=>!inMetro(s)), inside=ss.filter(inMetro);
  g+=draw0(outside, projS, 0.85, dim, rad)+draw0(inside, projS, 0.34, dim, rad);
  $("#mState").innerHTML=g;
  // ---- metro inset
  let m=`<rect width="${W.mw}" height="${W.mh}" rx="8" fill="#f8f8fa"/><path d="${polyPath(BAY,projM)}" fill="#e6edf5" stroke="#b7c3d1" stroke-width="1"/>`;
  const [mx,my]=projM(-37.81,144.96); m+=`<text x="${mx+10}" y="${my-10}" style="font-size:10px;fill:#8a96a6">Melbourne CBD</text>`;
  m+=`<text x="14" y="${W.mh-12}" style="font-size:10px;fill:#632ca6;font-weight:600">Metro Melbourne</text><text x="${W.mw-96}" y="${W.mh-110}" style="font-size:10px;fill:#8a96a6">Port Phillip Bay</text>`;
  m+=draw0(inside, projM, 1.0, dim, rad);
  $("#mMetro").innerHTML=m;
  // ---- chips, legend, selection card
  const regs=["Metro North","Metro East","Metro South","Metro West","Regional"];
  $("#mapChips").innerHTML=regs.map(r=>{const n=ss.filter(s=>s.region===r).reduce((a,s)=>a+s.n,0); return `<button class="mchip ${f.region===r?"on":""}" data-r="${r}">${r} <b>${n}</b></button>`;}).join("")+(f.region||f.account?`<button class="mchip clear" id="mapClear">Clear filter</button>`:"");
  $("#mapLegend").innerHTML = S.mapMode==="mix" ? OPENS.map(k=>`<span><i style="background:${STATUS_COLOR[k]}"></i>${k}</span>`).join("")
     : `<span><i style="background:#e34948"></i>Overdue</span><span><i style="background:#eb6834"></i>Next step due (letter / planning)</span><span><i style="background:#1baf7a"></i>On track</span>`;
  const tot=ss.reduce((a,s)=>a+s.n,0), cur=f.account?ss.find(s=>s.account===f.account):null;
  $("#selCard").innerHTML = cur ? `<div class="l" style="color:var(--ink-3)">SELECTED SITE</div><div style="font-weight:700;font-size:15px;line-height:1.2;margin:2px 0">${esc(cur.account)}</div><div class="sub">${cur.region} · ${cur.n} open work orders${cur.overdue?` · <b style="color:#b00">${cur.overdue} overdue</b>`:""}</div>
      <div style="margin-top:8px"><button class="btn sm" id="selWos">Open work orders</button> <button class="btn ghost sm" id="selClr">Clear</button></div>`
    : `<div class="l" style="color:var(--ink-3)">${f.region?esc(f.region.toUpperCase()):"ALL OF VICTORIA"}</div><div class="n" style="font-size:22px">${ss.filter(s=>!f.region||s.region===f.region).length} sites</div><div class="sub">Click a bubble or a territory chip to cross-filter every tile and chart below.</div>`;
  // ---- events
  $$("[data-site]").forEach(el=>el.onclick=e=>{ e.stopPropagation(); const a=el.dataset.site; setFilter(S.df.account===a?{}:{account:a}); });
  $$(".mchip[data-r]").forEach(b=>b.onclick=()=>setFilter(S.df.region===b.dataset.r?{}:{region:b.dataset.r}));
  if($("#mapClear")) $("#mapClear").onclick=()=>setFilter({}); if($("#selClr")) $("#selClr").onclick=()=>setFilter({});
  if($("#selWos")) $("#selWos").onclick=()=>{ S.wf={q:S.df.account,status:"",mod:"",region:"",action:false}; go("wos"); };
  $$("#mapMode button").forEach(b=>b.onclick=()=>{ S.mapMode=b.dataset.m; $$("#mapMode button").forEach(x=>x.classList.toggle("on",x===b)); drawMaps(); });
}
function draw0(list, proj, k, dim, rad) {
  return list.map(s=>{ const [x,y]=proj(s.lat,s.lon); return [s,x,y]; }).sort((a,b)=>b[0].n-a[0].n).map(([s,x,y])=>{
    const r=rad(s,k), sel=S.df.account===s.account;
    return (sel?`<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r+4}" fill="none" stroke="#632ca6" stroke-width="2.5"/>`:"")+
      pieSvg(+x.toFixed(1),+y.toFixed(1),r,siteSegs(s),`data-site="${esc(s.account)}" data-tip="${esc(siteTip(s))}" style="cursor:pointer;opacity:${dim(s)?.18:1}"`); }).join("");
}

/* ------------------------------------------------------------------ planner (gantt) */
const WD = () => { const [h1]=S.boot.work_day.start.split(":").map(Number), [h2]=S.boot.work_day.end.split(":").map(Number); return {h1,h2,len:h2-h1}; };
const leaveFor = (eng, ds) => S.boot.leave.find(l => l.engineer===eng && l.from<=ds && ds<=l.to);
const isHol = ds => S.boot.holidays.includes(ds);
function xOf(dt) { const {h1,len}=WD(); const d0=S.g.start; const days=Math.floor((new Date(dt.getFullYear(),dt.getMonth(),dt.getDate())-d0)/864e5);
  const h=dt.getHours()+dt.getMinutes()/60; return (days + (h-h1)/len) * S.g.px; }
function renderPlan() {
  const g=S.g, c=$("#v-plan");
  const mods=[...new Set(S.orders.map(o=>o.category))].sort(), regs=[...new Set(S.orders.map(o=>o.region))].sort();
  c.innerHTML = `
  <div class="toolbar">
    <div class="seg"><button id="gPrev">‹</button><button id="gToday">Today</button><button id="gNext">›</button></div>
    <strong id="gRange"></strong>
    <div class="seg" id="gZoom"><button data-d="7">Week</button><button data-d="14">2 weeks</button><button data-d="28">Month</button></div>
    <span class="muted small">Show:</span>
    ${["Proposed","Offered","Confirmed","Reschedule","Completed","Declined"].map(s=>`<label class="chip ${LIGHT_TEXT.has(s)?"light":""}" style="--c:${STATUS_COLOR[s]};cursor:pointer;opacity:${g.status.has(s)?1:.35}"><input type="checkbox" data-st="${s}" ${g.status.has(s)?"checked":""} hidden>${s}</label>`).join("")}
    <select id="gMod"><option value="">All categories</option>${mods.map(m=>`<option ${g.mod===m?"selected":""}>${m}</option>`).join("")}</select>
    <div class="spacer"></div>
    <button class="btn" id="gAuto">Auto-plan unplanned…</button>
  </div>
  <div class="gwrap"><div class="gscroll" id="gscroll"></div>
    <div class="backlog"><h2>Unplanned backlog <span class="muted small" id="blCount"></span></h2>
      <div class="f"><input id="blQ" placeholder="Search customer / system ID" value="${esc(S.bl.q)}">
        <select id="blMod"><option value="">All categories</option>${mods.map(m=>`<option ${S.bl.mod===m?"selected":""}>${m}</option>`).join("")}</select>
        <select id="blReg"><option value="">All territories</option>${regs.map(m=>`<option ${S.bl.region===m?"selected":""}>${m}</option>`).join("")}</select>
        <div class="muted small">Drag a job onto a technician's row. Drag bars to re-time or re-assign.</div></div>
      <div class="blist" id="blist"></div></div></div>`;
  $("#gPrev").onclick=()=>{g.start=addDays(g.start,-7); drawGantt();};
  $("#gNext").onclick=()=>{g.start=addDays(g.start,7); drawGantt();};
  $("#gToday").onclick=()=>{const t=parseD(S.boot.today); g.start=addDays(t,-((t.getDay()+6)%7)); drawGantt();};
  $$("#gZoom button").forEach(b=>{b.classList.toggle("on",+b.dataset.d===g.days); b.onclick=()=>{g.days=+b.dataset.d; g.px={7:150,14:100,28:58}[g.days]; renderPlan();};});
  $$("[data-st]").forEach(i=>i.onchange=()=>{i.checked?g.status.add(i.dataset.st):g.status.delete(i.dataset.st); renderPlan();});
  $("#gMod").onchange=e=>{g.mod=e.target.value; drawGantt(); drawBacklog();};
  $("#blQ").oninput=e=>{S.bl.q=e.target.value; drawBacklog();}; $("#blMod").onchange=e=>{S.bl.mod=e.target.value; drawBacklog();}; $("#blReg").onchange=e=>{S.bl.region=e.target.value; drawBacklog();};
  $("#gAuto").onclick=autoplanDialog;
  g.px={7:150,14:100,28:58}[g.days];
  drawGantt(); drawBacklog();
}
function visibleOrders() { const g=S.g; return S.orders.filter(o=>o.start && o.engineer && g.status.has(o.plan_status) && (!g.mod||o.category===g.mod)); }
function drawGantt() {
  const g=S.g, {h1,len}=WD(), px=g.px, W=px*g.days, box=$("#gscroll");
  const days=[...Array(g.days)].map((_,i)=>addDays(g.start,i));
  $("#gRange").textContent = days[0].toLocaleDateString("en-AU",{day:"numeric",month:"short"})+" – "+days[days.length-1].toLocaleDateString("en-AU",{day:"numeric",month:"short",year:"numeric"});
  const todayS=S.boot.today;
  let head=`<div class="ghead"><div class="glabel">Technician</div><div style="display:flex;width:${W}px">`+days.map(d=>{const ds=iso(d); const cls=[d.getDay()%6===0?"we":"",isHol(ds)?"hol":"",ds===todayS?"today":""].join(" ");
    return `<div class="gday ${cls}" style="width:${px}px">${d.toLocaleDateString("en-AU",{weekday:"short"})}<b>${d.getDate()}</b></div>`;}).join("")+`</div></div>`;
  const vis=visibleOrders().filter(o=>{const s=new Date(o.start); return s>=g.start && s<addDays(g.start,g.days);});
  let rows="";
  for (const e of S.boot.engineers) {
    const mine=vis.filter(o=>o.engineer===e.id).sort((a,b)=>a.start.localeCompare(b.start));
    const lanesEnd=[]; mine.forEach(o=>{const s=new Date(o.start).getTime(), en=new Date(o.end).getTime(); let l=lanesEnd.findIndex(t=>t<=s); if(l<0){l=lanesEnd.length;lanesEnd.push(0);} lanesEnd[l]=en; o._lane=l; o._ov=false;});
    mine.forEach(a=>mine.forEach(b=>{ if(a!==b && new Date(a.start)<new Date(b.end) && new Date(b.start)<new Date(a.end)) a._ov=true; }));
    const nl=Math.max(1,lanesEnd.length), h=nl*30+10;
    let bg=days.map((d,i)=>{const ds=iso(d), lv=leaveFor(e.id,ds); const cls=lv?"leave":isHol(ds)?"hol":d.getDay()%6===0?"we":"";
      return cls?`<div class="gbg ${cls}" style="left:${i*px}px;width:${px}px">${lv&&px>=100?esc(lv.label):""}</div>`:`<div class="gbg" style="left:${i*px}px;width:${px}px"></div>`;}).join("");
    const ti=days.findIndex(d=>iso(d)===todayS); if(ti>=0) bg+=`<div class="gtoday" style="left:${ti*px+px*0.5}px"></div>`;
    const bars=mine.map(o=>{const x=xOf(new Date(o.start)), w=Math.max(18,(o.duration_hrs/len)*px-2), late=o.start.slice(0,10)>o.pm_due;
      const lbl = w>70?`<b>${o.category}</b>${esc(o.account)}`:w>36?`<b>${o.category}</b>`:"";
      return `<div class="gbar ${LIGHT_TEXT.has(o.plan_status)?"light":""} ${o._ov?"bad":""} ${late?"late":""} ${o.plan_status==="Reschedule"?"dashed":""} ${S.selected===o.wo_number?"sel":""}" data-wo="${o.wo_number}"
        style="left:${x}px;top:${5+o._lane*30}px;width:${w}px;background:${STATUS_COLOR[o.plan_status]}"
        data-tip="<b>${esc(o.account)}</b><br>${o.category} · ${esc(o.product)}<br>${o.wo_number} · SID ${o.system_id}<br>${fmtDT(o.start)} – ${o.end.slice(11,16)} (${o.duration_hrs}h)<br>Due ${fmtD(o.pm_due)} · ${o.plan_status}${late?"<br><b>After PM due date</b>":""}${o._ov?"<br><b>Overlaps another job</b>":""}">${lbl}</div>`;}).join("");
    rows+=`<div class="grow" data-eng="${e.id}"><div class="glabel" style="height:${h}px" title="Skills: ${e.skills.join(", ")}"><b>${esc(e.name)}</b><span>${e.home} · ${e.skills.join(" ")}</span></div><div class="gcells" style="width:${W}px;height:${h}px">${bg}${bars}</div></div>`;
  }
  box.innerHTML = head+rows;
  $$(".gbar",box).forEach(b=>b.addEventListener("pointerdown", e=>startDrag(e, b.dataset.wo, "bar", b)));
}
function drawBacklog() {
  let list=S.orders.filter(o=>o.plan_status==="Unplanned");
  const q=S.bl.q.toLowerCase(); if(q) list=list.filter(o=>(o.account+o.system_id+o.wo_number).toLowerCase().includes(q));
  if(S.bl.mod||S.g.mod) list=list.filter(o=>o.category===(S.bl.mod||S.g.mod)); if(S.bl.region) list=list.filter(o=>o.region===S.bl.region);
  list.sort((a,b)=>a.pm_due.localeCompare(b.pm_due)||a.account.localeCompare(b.account));
  $("#blCount").textContent = `· ${list.length}`;
  const today=S.boot.today;
  $("#blist").innerHTML = list.slice(0,150).map(o=>`<div class="bitem" data-wo="${o.wo_number}" style="--c:${o.pm_due<today?"#e34948":"#9a9892"}">
    <b>${esc(o.account)}</b><div class="m">${o.category} · ${o.duration_hrs}h · ${o.region}</div><div class="m">Due ${fmtD(o.pm_due)}${o.pm_due<today?" · <b style='color:#b00'>overdue</b>":""}</div></div>`).join("") || `<div class="empty">All planned ✔</div>`;
  $$(".bitem").forEach(b=>b.addEventListener("pointerdown", e=>startDrag(e, b.dataset.wo, "backlog", b)));
}

/* drag & drop – one implementation for moving bars and dropping backlog jobs */
function startDrag(e, wo, src, el) {
  if (e.button!==0) return; e.preventDefault();
  const o=S.orders.find(x=>x.wo_number===wo), {h1,h2,len}=WD(), px=S.g.px;
  const r0=el.getBoundingClientRect(), gx=src==="bar"?e.clientX-r0.left:12, sx=e.clientX, sy=e.clientY; let ghost=null, moved=false, target=null;
  const w=Math.max(18,(o.duration_hrs/len)*px-2);
  const rowAt = (cx,cy) => { const cells=$$(".grow .gcells"); for(const c of cells){const r=c.getBoundingClientRect(); if(cy>=r.top&&cy<=r.bottom&&cx>=r.left-40&&cx<=r.right) return {c, r, eng:c.parentElement.dataset.eng};} return null; };
  const calc = (cx,cy) => { const row=rowAt(cx,cy); if(!row) return null; let x=cx-gx-row.r.left; let di=Math.floor((x+px*0.001)/px); let frac=(x-di*px)/px; let hrs=h1+frac*len;
    if(hrs<h1-0.25){ } hrs=Math.round(hrs*2)/2; if(hrs<h1) hrs=h1; if(hrs+o.duration_hrs>h2) hrs=Math.max(h1,h2-o.duration_hrs);
    di=Math.max(0,Math.min(S.g.days-1,di)); const d=addDays(S.g.start,di); const start=new Date(d.getFullYear(),d.getMonth(),d.getDate(),Math.floor(hrs),Math.round((hrs%1)*60));
    return {eng:row.eng, start, ds:iso(d), left:row.r.left+di*px+((hrs-h1)/len)*px}; };
  const quickBad = t => { const e=S.boot.engineers.find(x=>x.id===t.eng); const dow=t.start.getDay();
    return dow===0||dow===6||isHol(t.ds)||!!leaveFor(t.eng,t.ds)||!e.skills.includes(o.category); };
  const mv = ev => {
    if(!moved && Math.hypot(ev.clientX-sx,ev.clientY-sy)<5) return; moved=true;
    if(!ghost){ ghost=document.createElement("div"); ghost.className="dragghost"; ghost.style.width=w+"px"; ghost.style.background=STATUS_COLOR[o.plan_status]; ghost.textContent=o.category+" "+o.account; document.body.appendChild(ghost); el.style.opacity=.35; }
    target=calc(ev.clientX,ev.clientY);
    ghost.style.left=ev.clientX-gx+"px"; ghost.style.top=ev.clientY-13+"px";
    if(target){ ghost.classList.toggle("bad", quickBad(target)); ghost.textContent=`${o.category} ${target.start.toTimeString().slice(0,5)} · ${engName(target.eng).split(" ")[0]}`; }
  };
  const up = async ev => {
    window.removeEventListener("pointermove",mv); window.removeEventListener("pointerup",up);
    if(ghost) ghost.remove(); el.style.opacity=1;
    if(!moved){ openDrawer(wo); return; }
    if(!target) { if(src==="bar"){ /* dropped outside */ } return; }
    await placeOrder(o, target.eng, target.start);
  };
  window.addEventListener("pointermove",mv); window.addEventListener("pointerup",up);
}
async function placeOrder(o, eng, start, force=false) {
  const body={engineer:eng, start:start.getFullYear()+"-"+String(start.getMonth()+1).padStart(2,"0")+"-"+String(start.getDate()).padStart(2,"0")+"T"+start.toTimeString().slice(0,8), force};
  const r = await api(`orders/${o.wo_number}/move`, body);
  if(!r.saved){
    modal(`<h3>Check this booking</h3><p><b>${esc(o.account)}</b> · ${o.category} → ${esc(engName(eng))}, ${fmtDT(body.start)}</p>
      <div class="warnlist">${r.warnings.map(w=>`<div><b>${w.level==="error"?"Error":"Warning"}</b>${esc(w.msg)}</div>`).join("")}</div>
      <div class="row"><button class="btn danger" id="mForce">Book anyway</button><button class="btn ghost" id="mCancel">Cancel</button></div>`);
    $("#mForce").onclick=async()=>{closeModal(); await placeOrder(o,eng,start,true);}; $("#mCancel").onclick=closeModal; return;
  }
  const soft=r.warnings.filter(w=>w.level==="warn"); if(soft.length) toast("Warning: "+soft.map(w=>w.msg).join(" · "),5000); else toast("Scheduled "+o.account+" – "+fmtDT(body.start));
  await reloadAll(); if(S.view==="plan"){ drawGantt(); drawBacklog(); } if($("#drawer").classList.contains("on")) openDrawer(o.wo_number);
}
function autoplanDialog() {
  const n=S.orders.filter(o=>o.plan_status==="Unplanned").length;
  modal(`<h3>Auto-plan unplanned work</h3><p class="muted small">Places ${n} unplanned work orders onto engineers' calendars. Groups each customer's assets into one visit where possible, matches skills and territory, skips weekends, holidays and leave, and aims to land ~10 days before each PM falls due. Results are <b>Proposed</b> – nothing is sent to customers.</p>
    <div class="row"><label>Start planning from</label><input type="date" id="apFrom" value="${S.boot.today}"></div>
    <div class="row"><label>Notice (business days)</label><input type="number" id="apLead" value="5" min="0" max="30"></div>
    <div class="row"><label>Cluster by customer</label><input type="checkbox" id="apCl" checked></div>
    <div id="apRes" class="muted small"></div>
    <div class="row"><button class="btn" id="apRun">Plan ${n} work orders</button><button class="btn ghost" id="mCancel">Close</button></div>`);
  $("#mCancel").onclick=closeModal;
  $("#apRun").onclick=async()=>{ $("#apRes").textContent="Planning…";
    const r=await api("autoplan",{from:$("#apFrom").value,lead_days:+$("#apLead").value,cluster:$("#apCl").checked,commit:true});
    await reloadAll(); closeModal(); toast(`Placed ${r.placed.length} work orders${r.failed.length?` · ${r.failed.length} could not be placed (no skilled capacity in horizon)`:""}`,5000); renderPlan(); };
}

/* ------------------------------------------------------------------ drawer */
async function openDrawer(wo) {
  S.selected=wo; const o=S.orders.find(x=>x.wo_number===wo), d=$("#drawer");
  const act=await api("activity?wo="+wo);
  const statusBtns=["Confirmed","Reschedule","Declined","Completed"].map(s=>`<button class="btn ghost sm" data-set="${s}">${s}</button>`).join(" ");
  d.innerHTML=`<div style="display:flex;justify-content:space-between"><h3>${esc(o.account)}</h3><button class="btn ghost sm" id="dClose">Close</button></div>
    <div>${chip(o.plan_status)} <span class="muted small">${o.wo_number} · Case ${o.case_number}</span></div>
    ${o.suggest?`<div class="warnlist w" style="margin-top:10px">${esc(o.suggest)}${o.suggest_letter?` <button class="btn sm" id="dLetter" style="margin-left:6px">Prepare letter</button>`:""}</div>`:""}
    <div class="kv"><span>Equipment</span><span>${o.category} · ${esc(o.product)}</span><span>Asset / serial</span><span>${o.system_id} / ${o.serial}</span>
      <span>Site</span><span>${esc(o.address)}, ${esc(o.suburb)} ${o.postcode}<br><span class="muted">${o.region}</span></span>
      <span>Contract</span><span>${o.msa_number} (${fmtD(o.contract_start)} – ${fmtD(o.contract_end)})</span>
      <span>PM due</span><span>${fmtD(o.pm_due)} ${o.pm_sequence?`· schedule ${o.pm_sequence}`:""}</span>
      <span>Scheduled</span><span>${o.start?fmtDT(o.start)+" · "+o.duration_hrs+"h":"–"}</span><span>Engineer</span><span>${engName(o.engineer)}</span>
      <span>Contact</span><span>${esc(o.contact_name)}<br><span class="muted">${esc(o.contact_email)} · ${o.contact_phone}</span></span>
      <span>Letters sent</span><span>${o.attempts||0}${o.last_contact?` · last ${fmtD(o.last_contact)}`:""}</span>${o.decline_reason?`<span>Decline reason</span><span>${esc(o.decline_reason)}</span>`:""}</div>
    <div style="margin:8px 0">${statusBtns} ${o.start?`<button class="btn ghost sm" id="dUnsch">Remove from calendar</button>`:""}</div>
    <h2 style="margin-top:14px">Activity</h2>${act.map(a=>`<div class="actrow"><time>${a.ts.slice(5,16).replace("T"," ")}</time>${esc(a.kind)} ${esc(a.detail)}</div>`).join("")||`<div class="muted small">No activity yet</div>`}`;
  d.classList.add("on"); $("#dClose").onclick=closeDrawer;
  if($("#dLetter")) $("#dLetter").onclick=()=>openLetters(o.suggest_letter,[wo]);
  $$("[data-set]",d).forEach(b=>b.onclick=async()=>{ let reason; if(b.dataset.set==="Declined"){ reason=await askReason(); if(!reason) return; }
    await api(`orders/${wo}/status`,{status:b.dataset.set,reason}); await refreshView(); openDrawer(wo); });
  if($("#dUnsch")) $("#dUnsch").onclick=async()=>{ await api(`orders/${wo}/unschedule`,{}); await refreshView(); openDrawer(wo); };
}
function closeDrawer(){ $("#drawer").classList.remove("on"); S.selected=null; }
function askReason() { return new Promise(res=>{ modal(`<h3>Decline reason</h3><div class="row"><select id="rsn" style="flex:1;padding:6px">${S.boot.decline_reasons.map(r=>`<option>${esc(r)}</option>`).join("")}</select></div>
  <div class="row"><button class="btn" id="mOk">Save</button><button class="btn ghost" id="mCancel">Cancel</button></div>`); $("#mOk").onclick=()=>{const v=$("#rsn").value; closeModal(); res(v);}; $("#mCancel").onclick=()=>{closeModal();res(null);}; }); }
function modal(html){ $("#modal").innerHTML=html; $("#modalBg").classList.add("on"); }
function closeModal(){ $("#modalBg").classList.remove("on"); }

/* ------------------------------------------------------------------ work orders */
function filteredWos() {
  const f=S.wf, q=(f.q||"").toLowerCase(), today=S.boot.today;
  return S.orders.filter(o=>(!f.status||o.plan_status===f.status) && (!f.mod||o.category===f.mod) && (!f.region||o.region===f.region)
    && (!q||(o.account+o.system_id+o.wo_number+o.serial+o.case_number).toLowerCase().includes(q))
    && (!f.overdue||(o.pm_due<today&&!["Completed","Confirmed","Closed"].includes(o.plan_status)))
    && (!f.action||o.suggest) && (f.status||f.overdue||f.q||!["Closed"].includes(o.plan_status)));
}
function renderWos() {
  const c=$("#v-wos"), f=S.wf, mods=[...new Set(S.orders.map(o=>o.category))].sort(), regs=[...new Set(S.orders.map(o=>o.region))].sort();
  c.innerHTML=`<div class="toolbar"><input type="text" id="wQ" placeholder="Search customer, system ID, WO, serial…" value="${esc(f.q)}" style="width:290px">
    <select id="wS"><option value="">All statuses</option>${S.boot.statuses.map(s=>`<option ${f.status===s?"selected":""}>${s}</option>`).join("")}</select>
    <select id="wM"><option value="">All categories</option>${mods.map(m=>`<option ${f.mod===m?"selected":""}>${m}</option>`).join("")}</select>
    <select id="wR"><option value="">All territories</option>${regs.map(m=>`<option ${f.region===m?"selected":""}>${m}</option>`).join("")}</select>
    <label><input type="checkbox" id="wA" ${f.action?"checked":""}> Needs action</label>${f.overdue?`<span class="chip" style="--c:#e34948">Overdue only ×</span>`:""}
    <div class="spacer"></div><span class="muted small" id="wCount"></span>
    <select id="wL">${S.boot.letters.map(l=>`<option value="${l.key}">${l.label}</option>`).join("")}</select>
    <button class="btn" id="wGo">Letters for selected</button><button class="btn ghost" id="wPlan">Auto-plan selected</button></div>
    <div class="card" style="padding:0"><div class="scroll" style="max-height:calc(100vh - 230px)"><table class="t" id="wT"></table></div></div>`;
  const upd=()=>{ Object.assign(f,{q:$("#wQ").value,status:$("#wS").value,mod:$("#wM").value,region:$("#wR").value,action:$("#wA").checked}); drawWos(); };
  ["#wQ","#wS","#wM","#wR","#wA"].forEach(s=>$(s).oninput=upd);
  $("#wGo").onclick=()=>{ if(!S.sel.size) return toast("Select some work orders first"); openLetters($("#wL").value,[...S.sel]); };
  $("#wPlan").onclick=async()=>{ const w=[...S.sel].filter(x=>S.orders.find(o=>o.wo_number===x).plan_status==="Unplanned"); if(!w.length) return toast("Select unplanned work orders");
    const r=await api("autoplan",{wos:w,from:S.boot.today,lead_days:5,commit:true}); toast(`Placed ${r.placed.length} · failed ${r.failed.length}`); S.sel.clear(); await refreshView(); };
  drawWos();
}
function drawWos() {
  const rows=filteredWos(); $("#wCount").textContent=`${rows.length} work orders · ${S.sel.size} selected`;
  const today=S.boot.today;
  $("#wT").innerHTML=`<tr><th><input type="checkbox" id="wAll"></th><th>Work order</th><th>Customer</th><th>Type</th><th>Asset ID</th><th>Territory</th><th>PM due</th><th>Status</th><th>Scheduled</th><th>Technician</th><th>Letters</th><th>Next step</th></tr>`+
    rows.slice(0,400).map(o=>`<tr data-wo="${o.wo_number}" style="cursor:pointer"><td><input type="checkbox" class="wc" ${S.sel.has(o.wo_number)?"checked":""}></td><td class="mono">${o.wo_number}</td><td>${esc(o.account)}</td><td>${o.category}</td><td class="mono">${o.system_id}</td><td>${o.region}</td>
      <td style="${o.pm_due<today&&!["Completed","Confirmed"].includes(o.plan_status)?"color:#b00;font-weight:600":""}">${fmtD(o.pm_due)}</td><td>${chip(o.plan_status)}</td><td>${fmtDT(o.start)}</td><td>${engName(o.engineer)}</td><td>${o.attempts||0}</td><td class="small">${esc(o.suggest||"")}</td></tr>`).join("");
  $$("#wT tr[data-wo]").forEach(tr=>tr.onclick=e=>{ if(e.target.classList.contains("wc")){ const w=tr.dataset.wo; e.target.checked?S.sel.add(w):S.sel.delete(w); $("#wCount").textContent=`${rows.length} work orders · ${S.sel.size} selected`; return; } openDrawer(tr.dataset.wo); });
  $("#wAll").onchange=e=>{ rows.slice(0,400).forEach(o=>e.target.checked?S.sel.add(o.wo_number):S.sel.delete(o.wo_number)); drawWos(); };
}

/* ------------------------------------------------------------------ letters */
function openLetters(key, wos) { S.letter={key, wos:[...wos], previews:[], skip:new Set()}; go("letters"); }
async function renderLetters() {
  const c=$("#v-letters"), L=S.letter, b=S.boot;
  const queue={}; S.orders.forEach(o=>{ if(o.suggest_letter){ (queue[o.suggest_letter]??=[]).push(o.wo_number); }});
  c.innerHTML=`<div class="letters"><div class="card"><h2>Letter</h2>
    <select id="lKey" style="width:100%;padding:6px;margin-bottom:10px">${b.letters.map(l=>`<option value="${l.key}" ${L.key===l.key?"selected":""}>${l.label}</option>`).join("")}</select>
    <div class="small" style="margin-bottom:10px"><b id="lCount">${L.wos.length}</b> work orders selected → one letter per customer.</div>
    <div class="muted small" style="margin-bottom:6px">Load what's waiting:</div>
    ${Object.entries(queue).map(([k,w])=>`<div><button class="btn ghost sm" data-load="${k}" style="margin:2px 0;width:100%;text-align:left">${(b.letters.find(l=>l.key===k)||{}).label} · ${w.length} WOs</button></div>`).join("")||`<div class="muted small">Nothing queued.</div>`}
    <h2 style="margin-top:16px">Output</h2>
    <label class="small"><input type="radio" name="lMode" value="display" checked> Open in Outlook (review &amp; send yourself)</label><br>
    <label class="small"><input type="radio" name="lMode" value="draft"> Save to Outlook Drafts</label><br>
    <label class="small"><input type="radio" name="lMode" value="eml"> Save .eml files (no Outlook needed)</label><br>
    <label class="small"><input type="radio" name="lMode" value="send" ${b.outlook.allow_send?"":"disabled"}> Send immediately ${b.outlook.allow_send?"":"(disabled in config)"}</label>
    <div class="muted small" style="margin:6px 0">${b.outlook.com?"Outlook detected – drafts are created in your mailbox.":"Outlook COM not found on this machine – files are written as .eml drafts (open with Outlook), plus a .docx copy of each letter."}</div>
    <label class="small"><input type="checkbox" id="lUpd" checked> Update planning status after generating</label>
    <div style="margin-top:12px"><button class="btn" id="lGen">Create letters</button></div><div id="lRes" class="small" style="margin-top:10px"></div></div>
    <div><div id="lPrev"><div class="empty">Loading preview…</div></div></div></div>`;
  $("#lKey").onchange=e=>{L.key=e.target.value; drawPreview();};
  $$("[data-load]").forEach(x=>x.onclick=()=>{ L.key=x.dataset.load; L.wos=queue[x.dataset.load]; L.skip=new Set(); renderLetters(); });
  $("#lGen").onclick=generateLetters;
  drawPreview();
}
async function drawPreview() {
  const L=S.letter, el=$("#lPrev"); if(!L.wos.length){ el.innerHTML=`<div class="card empty">Pick work orders on the <b>Work orders</b> tab, or load a queue on the left.</div>`; return; }
  L.previews=await api("letters/preview",{wos:L.wos,letter:L.key}); $("#lCount").textContent=L.wos.length;
  el.innerHTML=`<div class="muted small" style="margin-bottom:6px">${L.previews.length} letters · click a header to collapse · untick to skip</div>`+L.previews.map((p,i)=>`<div class="lcard ${L.skip.has(p.account)?"off":""}"><header data-i="${i}"><input type="checkbox" class="lk" data-a="${esc(p.account)}" ${L.skip.has(p.account)?"":"checked"}><b>${esc(p.account)}</b><span class="muted">${p.wos.length} asset${p.wos.length>1?"s":""} → ${esc(p.to||"NO EMAIL ADDRESS")}</span>
    ${p.unscheduled.length?`<span class="chip" style="--c:#e34948">${p.unscheduled.length} not scheduled</span>`:""}</header><div class="small" style="padding:6px 10px;border-bottom:1px solid var(--line)"><b>Subject:</b> ${esc(p.subject)}</div><iframe sandbox srcdoc="${esc(p.html)}"></iframe></div>`).join("");
  $$(".lcard header",el).forEach(h=>h.onclick=e=>{ if(e.target.classList.contains("lk")) return; h.parentElement.classList.toggle("off"); });
  $$(".lk",el).forEach(k=>k.onchange=()=>{ k.checked?L.skip.delete(k.dataset.a):L.skip.add(k.dataset.a); k.closest(".lcard").classList.toggle("off",!k.checked); });
}
async function generateLetters() {
  const L=S.letter, wos=S.letter.previews.filter(p=>!L.skip.has(p.account)).flatMap(p=>p.wos);
  if(!wos.length) return toast("Nothing to create");
  const mode=($("input[name=lMode]:checked")||{}).value||"display";
  if(mode==="send" && !confirm(`Send ${L.previews.length} email(s) immediately?`)) return;
  $("#lRes").textContent="Creating…";
  try { const r=await api("letters/generate",{wos,letter:L.key,mode,update_status:$("#lUpd").checked});
    $("#lRes").innerHTML=`<b>${r.items.length} letters created</b> via ${r.engine}.${r.note?`<div class="muted">${esc(r.note)}</div>`:""}<ul>${r.items.map(i=>`<li>${esc(i.to)}${i.file?`<br><span class="muted">${esc(i.file)}</span>`:""}</li>`).join("")}</ul><div class="muted">Word copies:<br>${r.docx.map(esc).join("<br>")}</div>`;
    await reloadAll(); toast(`${r.items.length} letters created`);
  } catch(e){ $("#lRes").textContent=e.message; }
}

/* ------------------------------------------------------------------ data & export */
async function renderData() {
  const b=S.boot, act=await api("activity");
  const cm = await fetch("/api/bootstrap").then(r=>r.json());
  $("#v-data").innerHTML=`<div class="grid cols-2"><div class="card"><h2>Report source</h2>
    <div class="kv"><span>Type</span><span>${esc(b.source.type)} (report export from your field service system)</span><span>Path</span><span><code>${esc(b.source.path)}</code></span><span>Sheet</span><span>${esc(b.source.sheet)}</span><span>Last refresh</span><span>${S.dash.last_refresh||"–"}</span></div>
    <p class="small muted">Point <code>config.json → source.path</code> at the scheduled report export (e.g. a SharePoint/OneDrive-synced .xlsx or .csv). <b>Refresh</b> re-reads it: new work orders arrive as <i>Unplanned</i>, existing ones keep their planned dates, engineer and letter history, and anything that drops off the open-PM report is marked <i>Completed</i>. Column names are mapped in <code>column_map</code>.</p>
    <div class="toolbar"><button class="btn" id="dRef">Refresh from report</button><button class="btn ghost" id="dDrift">Demo: simulate overnight refresh</button></div>
    <h2 style="margin-top:16px">Schedule round-trip</h2><p class="small muted">Download the planned schedule as a CSV (work order, start, end, technician, status) shaped for a data load back into the source system.</p>
    <a class="btn" href="/api/export/schedule">Download schedule import (.csv)</a></div>
    <div class="card"><h2>Recent activity</h2><div class="scroll" style="max-height:480px">${act.map(a=>`<div class="actrow"><time>${a.ts.slice(5,16).replace("T"," ")}</time><b>${esc(a.wo_number)}</b> ${esc(a.kind)} ${esc(a.detail)}</div>`).join("")}</div></div></div>`;
  $("#dRef").onclick=doRefresh;
  $("#dDrift").onclick=async()=>{ const r=await api("demo/drift",{}); toast(`Simulated refresh: +${r.simulated_new} new work orders, ${r.removed} completed in source`,5000); await refreshView(); };
}
init().catch(e=>{ document.body.insertAdjacentHTML("beforeend",`<pre style="color:#b00;padding:20px">${esc(e.stack||e)}</pre>`); });
