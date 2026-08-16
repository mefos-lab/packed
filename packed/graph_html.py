"""Self-contained interactive rendering of a connection graph.

Written as one HTML file with no external requests, because the output
is an artefact someone keeps: it has to still work when opened from a
thumb drive in two years, offline, with the CDN long gone.

**Every display decision here is an argument about evidence.** The
graph's whole claim is that two entities are connected by N separate
routes, and a viewer will read weight into whatever is drawn heaviest.
So:

- Edge style encodes the *kind* of claim, never the size of a number.
  Attributable edges are solid, routes dashed, leads dotted. A thick
  dashed line would suggest a large amount travelling a path where no
  amount can travel at all.
- A node resolved by name carries a visible mark. `fec:C00799031` is
  exact; `vendor:mission-control` is onoma's guess and can be wrong in
  both directions, which changes how much a path through it is worth.
- Paths are listed and counted, never summed. There is deliberately no
  total anywhere in this interface.
- A shared commodity vendor is structurally identical to a shared
  consultancy and evidentially worthless. The panel shows each
  intermediary's share of both sides' spending so the difference is
  visible, and says plainly that a low share means nothing.
"""

from __future__ import annotations

import json
from typing import Any

from .graph import ATTRIBUTABLE, LEAD, ROUTE, ConnectionGraph

_TEMPLATE = """<!doctype html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    --paper:#F3F4F1; --surface:#FFFFFF; --sunk:#EDEEE9;
    --ink:#15181B; --ink-soft:#565C63; --rule:#DCDFD8;
    --teal:#0B6E63; --slate:#7A828B; --flag:#B25317; --brass:#96702A;
    --data: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
    --body: ui-sans-serif, system-ui, "Helvetica Neue", Arial, sans-serif;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --paper:#0F1214; --surface:#171B1E; --sunk:#13171A;
      --ink:#E9EBE6; --ink-soft:#98A0A7; --rule:#292E32;
      --teal:#3FA79A; --slate:#7E8790; --flag:#E08048; --brass:#C9A055;
    }
  }
  :root[data-theme="dark"] {
    --paper:#0F1214; --surface:#171B1E; --sunk:#13171A;
    --ink:#E9EBE6; --ink-soft:#98A0A7; --rule:#292E32;
    --teal:#3FA79A; --slate:#7E8790; --flag:#E08048; --brass:#C9A055;
  }
  * { box-sizing:border-box; }
  body {
    margin:0; background:var(--paper); color:var(--ink);
    font-family:var(--body); font-size:15px; line-height:1.55;
  }
  header {
    padding:18px 24px; border-bottom:2px solid var(--ink);
    display:flex; flex-wrap:wrap; gap:16px; align-items:baseline;
  }
  header h1 { font-size:19px; margin:0; letter-spacing:-.01em; }
  header .sub { font-family:var(--data); font-size:11.5px; color:var(--ink-soft); }
  header .spacer { flex:1 1 auto; }
  button, select {
    font-family:var(--data); font-size:11.5px; padding:6px 10px;
    background:var(--surface); color:var(--ink); border:1px solid var(--rule);
    cursor:pointer;
  }
  button:hover, select:hover { border-color:var(--brass); }
  button:focus-visible, select:focus-visible, [tabindex]:focus-visible {
    outline:2px solid var(--brass); outline-offset:2px;
  }
  button[aria-pressed="true"] { background:var(--ink); color:var(--paper); border-color:var(--ink); }

  .layout { display:grid; grid-template-columns:1fr 380px; min-height:calc(100vh - 62px); }
  @media (max-width:900px) { .layout { grid-template-columns:1fr; } }

  #stage { position:relative; background:var(--surface); border-right:1px solid var(--rule); }
  #stage svg { display:block; width:100%; height:100%; min-height:520px; cursor:grab; }
  #stage svg.dragging { cursor:grabbing; }

  aside { padding:20px 22px 60px; overflow-y:auto; max-height:calc(100vh - 62px); }
  aside h2 {
    font-family:var(--data); font-size:10.5px; letter-spacing:.14em;
    text-transform:uppercase; color:var(--ink-soft); margin:26px 0 10px; font-weight:600;
  }
  aside h2:first-child { margin-top:0; }
  aside p { margin:0 0 12px; font-size:13.5px; color:var(--ink-soft); }
  aside p.lead { color:var(--ink); }

  .why {
    background:var(--sunk); border-left:3px solid var(--brass);
    padding:12px 14px; margin:0 0 14px; font-size:13px;
  }
  .why strong { color:var(--ink); }

  .legend-row { display:flex; align-items:center; gap:10px; margin-bottom:12px; font-size:13px; }
  .legend-row .k { width:34px; flex:none; }
  .legend-row .t { color:var(--ink-soft); }
  .legend-row .t b { color:var(--ink); display:block; font-size:12.5px; }

  .kv { font-family:var(--data); font-size:12px; }
  .kv div { display:grid; grid-template-columns:112px 1fr; gap:10px; padding:5px 0;
            border-bottom:1px solid var(--rule); }
  .kv span:first-child { color:var(--ink-soft); }
  .num { font-variant-numeric:tabular-nums; }

  .chip {
    display:inline-block; font-family:var(--data); font-size:10px; letter-spacing:.08em;
    text-transform:uppercase; padding:2px 7px; border:1px solid currentColor; font-weight:600;
  }
  .chip.exact { color:var(--teal); }
  .chip.resolved { color:var(--brass); }

  .path {
    border:1px solid var(--rule); padding:12px 14px; margin-bottom:10px; background:var(--surface);
  }
  .path .hd {
    font-family:var(--data); font-size:10.5px; letter-spacing:.1em; text-transform:uppercase;
    font-weight:700; margin-bottom:8px;
  }
  .path.attributable .hd { color:var(--teal); }
  .path.route .hd { color:var(--slate); }
  .path.lead .hd { color:var(--flag); }
  .path ol { margin:0; padding-left:16px; font-size:12.5px; font-family:var(--data); }
  .path li { margin-bottom:4px; }
  .path .rel { color:var(--ink-soft); }
  .path .warn { margin-top:8px; font-size:12px; color:var(--flag); }

  .empty { font-size:13px; color:var(--ink-soft); font-style:italic; }
  .picker { display:flex; gap:8px; margin-bottom:12px; }
  .picker select { flex:1 1 auto; min-width:0; }

  svg text { font-family:var(--data); fill:var(--ink); pointer-events:none; }
  .nlabel { font-size:10.5px; font-weight:600; }
  .elabel { font-size:9px; fill:var(--ink-soft); }
  .node circle { cursor:pointer; }
  .dim { opacity:.13; }
</style>
</head>
<body>

<header>
  <h1>__HEADING__</h1>
  <span class="sub">__SUBHEAD__</span>
  <span class="spacer"></span>
  <button id="t-attributable" aria-pressed="true">amounts</button>
  <button id="t-route" aria-pressed="true">routes</button>
  <button id="t-lead" aria-pressed="true">leads</button>
  <button id="t-labels" aria-pressed="true">labels</button>
  <button id="t-theme">theme</button>
</header>

<div class="layout">
  <div id="stage"><svg id="canvas"></svg></div>
  <aside>
    <h2>What you are looking at</h2>
    <p class="lead">__INTRO__</p>
    <div class="why">
      <strong>Why this is a connection graph and not a money-flow diagram.</strong>
      Money entering an intermediary committee is commingled — it sits in one account
      with everything else raised, so no part of what comes out is traceable to any
      particular donor. Connectivity survives that; amounts do not. Every edge below
      therefore declares which kind of claim it is, and nothing here is ever summed
      along a path.
    </div>

    <h2>Reading the edges</h2>
    <div class="legend-row">
      <svg class="k" height="12" viewBox="0 0 34 12"><line x1="0" y1="6" x2="34" y2="6" stroke="var(--teal)" stroke-width="3.5"/></svg>
      <span class="t"><b>Attributable</b>A disclosed amount between two named parties.</span>
    </div>
    <div class="legend-row">
      <svg class="k" height="12" viewBox="0 0 34 12"><line x1="0" y1="6" x2="34" y2="6" stroke="var(--slate)" stroke-width="2.5" stroke-dasharray="6 4"/></svg>
      <span class="t"><b>Route only</b>A real link carrying no amount. Anything past a commingled hop.</span>
    </div>
    <div class="legend-row">
      <svg class="k" height="12" viewBox="0 0 34 12"><line x1="0" y1="6" x2="34" y2="6" stroke="var(--flag)" stroke-width="2.5" stroke-dasharray="1 4" stroke-linecap="round"/></svg>
      <span class="t"><b>Lead</b>A shape worth checking. Lawful activity produces the same picture.</span>
    </div>
    <p>Line thickness never encodes an amount — only the kind of claim. Click any node
       for its detail; drag to rearrange.</p>

    <h2>Find routes between two entities</h2>
    <p>Several separate routes between the same pair is the finding. One is ordinary.</p>
    <div class="picker">
      <select id="from"></select>
      <select id="to"></select>
    </div>
    <button id="findpaths" style="width:100%">Show every route</button>
    <div id="paths" style="margin-top:14px"></div>

    <h2 id="sel-h">Selection</h2>
    <div id="selection"><p class="empty">Click a node in the graph.</p></div>

    <h2>Limits of this view</h2>
    <div id="warnings"></div>
  </aside>
</div>

<script>
const DATA = __DATA__;
const KIND_COLOR = { attributable:"var(--teal)", route:"var(--slate)", lead:"var(--flag)" };
const show = { attributable:true, route:true, lead:true, labels:true };

const svg = document.getElementById("canvas");
const NS = "http://www.w3.org/2000/svg";
let W = 900, H = 620;

// ---- layout: a small force simulation, run to rest before first paint so
// the graph does not writhe while being read.
const nodes = DATA.nodes.map((n, i) => ({
  ...n,
  x: W/2 + 240*Math.cos(2*Math.PI*i/DATA.nodes.length),
  y: H/2 + 240*Math.sin(2*Math.PI*i/DATA.nodes.length),
  vx:0, vy:0,
}));
const index = new Map(nodes.map(n => [n.id, n]));
const links = DATA.edges
  .filter(e => index.has(e.source) && index.has(e.target))
  .map(e => ({ ...e, s:index.get(e.source), t:index.get(e.target) }));

const degree = new Map();
links.forEach(l => {
  degree.set(l.s.id, (degree.get(l.s.id)||0)+1);
  degree.set(l.t.id, (degree.get(l.t.id)||0)+1);
});

function simulate(steps) {
  for (let step=0; step<steps; step++) {
    for (let i=0;i<nodes.length;i++) {
      for (let j=i+1;j<nodes.length;j++) {
        const a=nodes[i], b=nodes[j];
        let dx=b.x-a.x, dy=b.y-a.y;
        let d2=dx*dx+dy*dy || 0.01;
        const rep = 5200/d2;
        const d=Math.sqrt(d2);
        const fx=rep*dx/d, fy=rep*dy/d;
        a.vx-=fx; a.vy-=fy; b.vx+=fx; b.vy+=fy;
      }
    }
    links.forEach(l => {
      let dx=l.t.x-l.s.x, dy=l.t.y-l.s.y;
      const d=Math.sqrt(dx*dx+dy*dy)||0.01;
      const f=(d-155)*0.012;
      const fx=f*dx/d, fy=f*dy/d;
      l.s.vx+=fx; l.s.vy+=fy; l.t.vx-=fx; l.t.vy-=fy;
    });
    nodes.forEach(n => {
      n.vx += (W/2-n.x)*0.0016;
      n.vy += (H/2-n.y)*0.0016;
      n.vx*=0.82; n.vy*=0.82;
      if (!n.pinned) { n.x+=n.vx; n.y+=n.vy; }
      n.x=Math.max(70,Math.min(W-70,n.x));
      n.y=Math.max(40,Math.min(H-40,n.y));
    });
  }
}
simulate(420);

function radius(n){ return 6 + Math.min(9, (degree.get(n.id)||1)*1.4); }
function nodeColor(n){
  if (n.kind==="vendor") return "var(--brass)";
  if (n.kind==="congressional_committee") return "var(--ink)";
  if (n.kind==="contributor" || n.kind==="lobbyist") return "var(--slate)";
  return "var(--teal)";
}

let highlight = null;   // Set of node ids, or null

function draw() {
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  while (svg.firstChild) svg.removeChild(svg.firstChild);

  links.forEach(l => {
    if (!show[l.kind]) return;
    const on = !highlight || (highlight.has(l.s.id) && highlight.has(l.t.id));
    const line = document.createElementNS(NS,"line");
    line.setAttribute("x1",l.s.x); line.setAttribute("y1",l.s.y);
    line.setAttribute("x2",l.t.x); line.setAttribute("y2",l.t.y);
    line.setAttribute("stroke", KIND_COLOR[l.kind]);
    line.setAttribute("stroke-width", l.kind==="attributable" ? 3 : 2);
    if (l.kind==="route") line.setAttribute("stroke-dasharray","6 4");
    if (l.kind==="lead") { line.setAttribute("stroke-dasharray","1 4"); line.setAttribute("stroke-linecap","round"); }
    if (!on) line.setAttribute("class","dim");
    svg.appendChild(line);

    if (show.labels && on && l.amount) {
      const tx=document.createElementNS(NS,"text");
      tx.setAttribute("class","elabel");
      tx.setAttribute("x",(l.s.x+l.t.x)/2); tx.setAttribute("y",(l.s.y+l.t.y)/2-4);
      tx.setAttribute("text-anchor","middle");
      tx.textContent = "$" + Math.round(l.amount).toLocaleString();
      svg.appendChild(tx);
    }
  });

  nodes.forEach(n => {
    const on = !highlight || highlight.has(n.id);
    const g=document.createElementNS(NS,"g");
    g.setAttribute("class","node" + (on?"":" dim"));
    const c=document.createElementNS(NS,"circle");
    c.setAttribute("cx",n.x); c.setAttribute("cy",n.y); c.setAttribute("r",radius(n));
    c.setAttribute("fill", nodeColor(n));
    if (n.identity==="resolved-by-name") {
      c.setAttribute("stroke","var(--paper)");
      c.setAttribute("stroke-width","2");
      c.setAttribute("stroke-dasharray","3 2");
    }
    c.setAttribute("tabindex","0");
    c.setAttribute("role","button");
    c.setAttribute("aria-label",n.label);
    c.addEventListener("click", ()=>select(n));
    c.addEventListener("keydown", ev=>{ if(ev.key==="Enter"||ev.key===" "){ev.preventDefault();select(n);} });
    c.addEventListener("mousedown", ev=>startDrag(ev,n));
    g.appendChild(c);
    if (show.labels) {
      const t=document.createElementNS(NS,"text");
      t.setAttribute("class","nlabel");
      t.setAttribute("x",n.x); t.setAttribute("y",n.y-radius(n)-5);
      t.setAttribute("text-anchor","middle");
      t.textContent = n.label.length>26 ? n.label.slice(0,25)+"\\u2026" : n.label;
      g.appendChild(t);
    }
    svg.appendChild(g);
  });
}

let drag=null;
function startDrag(ev,n){
  ev.preventDefault();
  drag={n};
  svg.classList.add("dragging");
}
svg.addEventListener("mousemove", ev=>{
  if(!drag) return;
  const r=svg.getBoundingClientRect();
  drag.n.x=(ev.clientX-r.left)/r.width*W;
  drag.n.y=(ev.clientY-r.top)/r.height*H;
  drag.n.pinned=true;
  draw();
});
window.addEventListener("mouseup", ()=>{ drag=null; svg.classList.remove("dragging"); });

function money(v){ return v==null ? "\\u2014" : "$"+Math.round(v).toLocaleString(); }

function select(n){
  highlight = new Set([n.id]);
  links.forEach(l => {
    if (l.s.id===n.id) highlight.add(l.t.id);
    if (l.t.id===n.id) highlight.add(l.s.id);
  });
  const conn = links.filter(l => l.s.id===n.id || l.t.id===n.id);
  const chip = n.identity==="exact"
    ? '<span class="chip exact">exact identifier</span>'
    : '<span class="chip resolved">matched by name</span>';
  const idNote = n.identity==="exact"
    ? "Joined on a filed identifier, so this node is the entity it says it is."
    : "Resolved from a name string. It can merge two entities that share a name, or miss one written differently \\u2014 weigh any route through it accordingly.";

  let detail = "";
  for (const [k,v] of Object.entries(n.detail||{})) {
    if (v===null || v===undefined || v==="" || (Array.isArray(v)&&!v.length)) continue;
    detail += `<div><span>${k.replace(/_/g," ")}</span><span>${Array.isArray(v)?v.join(", "):v}</span></div>`;
  }

  document.getElementById("sel-h").textContent = "Selection";
  document.getElementById("selection").innerHTML = `
    <p class="lead"><strong>${n.label}</strong></p>
    <p>${chip} &nbsp; <span style="font-family:var(--data);font-size:11.5px">${n.kind.replace(/_/g," ")}</span></p>
    <p>${idNote}</p>
    ${detail ? `<div class="kv">${detail}</div>` : ""}
    <h2 style="margin-top:18px">${conn.length} connection${conn.length===1?"":"s"}</h2>
    <div class="kv">${conn.map(l => {
      const other = l.s.id===n.id ? l.t : l.s;
      const dir = l.s.id===n.id ? "\\u2192" : "\\u2190";
      return `<div><span>${l.relation}</span><span>${dir} ${other.label}${l.amount?` &middot; <span class="num">${money(l.amount)}</span>`:""}</span></div>`;
    }).join("")}</div>`;
  draw();
}

// ---- path finding, mirroring the server-side search
function neighbours(id){
  const out=[];
  links.forEach(l=>{
    if(!show[l.kind]) return;
    if(l.s.id===id) out.push([l.t.id,l]);
    else if(l.t.id===id) out.push([l.s.id,l]);
  });
  return out;
}
function findPaths(a,b,maxHops=4,limit=30){
  if(a===b) return [];
  const found=[]; const q=[[a,[a],[]]];
  while(q.length && found.length<limit){
    const [cur,seen,taken]=q.shift();
    if(taken.length>=maxHops) continue;
    for(const [nb,edge] of neighbours(cur)){
      if(seen.includes(nb)) continue;
      if(nb===b) found.push({nodes:seen.concat([nb]), edges:taken.concat([edge])});
      else q.push([nb,seen.concat([nb]),taken.concat([edge])]);
    }
  }
  return found;
}
function weakest(p){
  if(p.edges.some(e=>e.kind==="lead")) return "lead";
  if(p.edges.some(e=>e.kind==="route")) return "route";
  return "attributable";
}

const fromSel=document.getElementById("from"), toSel=document.getElementById("to");
nodes.slice().sort((a,b)=>a.label.localeCompare(b.label)).forEach(n=>{
  [fromSel,toSel].forEach(sel=>{
    const o=document.createElement("option"); o.value=n.id; o.textContent=n.label; sel.appendChild(o);
  });
});
if (DATA.suggest && DATA.suggest.length===2){
  fromSel.value=DATA.suggest[0]; toSel.value=DATA.suggest[1];
}

document.getElementById("findpaths").addEventListener("click", ()=>{
  const a=fromSel.value, b=toSel.value;
  const paths=findPaths(a,b);
  const box=document.getElementById("paths");
  if(!paths.length){
    box.innerHTML='<p class="empty">No route found within four hops using the edge kinds currently shown.</p>';
    highlight=null; draw(); return;
  }
  paths.sort((p,q)=>p.edges.length-q.edges.length);
  const lit=new Set(); paths.forEach(p=>p.nodes.forEach(n=>lit.add(n)));
  highlight=lit; draw();

  box.innerHTML = `<p class="lead">${paths.length} route${paths.length===1?"":"s"} within four hops.
    Several separate routes is the finding; a single one is ordinary. These are listed,
    never added together \\u2014 the same money often appears in more than one.</p>` +
    paths.map(p=>{
      const k=weakest(p);
      const via=p.nodes.slice(1,-1).map(id=>index.get(id));
      const commodity=via.filter(v=>v && v.detail &&
        typeof v.detail.share_of_sampled_outside_spending==="number" &&
        v.detail.share_of_sampled_outside_spending < 0.1);
      const steps=p.edges.map((e,i)=>{
        const from=index.get(p.nodes[i]), to=index.get(p.nodes[i+1]);
        return `<li>${from.label} <span class="rel">${e.relation}</span> ${to.label}${
          e.amount?` <span class="num">&middot; ${money(e.amount)}</span>`:""}</li>`;
      }).join("");
      return `<div class="path ${k}">
        <div class="hd">${p.edges.length} hop${p.edges.length===1?"":"s"} &middot; weakest link: ${k}</div>
        <ol>${steps}</ol>
        ${commodity.length?`<div class="warn">Runs through ${commodity.map(c=>c.label).join(", ")},
          which took under 0.1% of the outside committee's spending. Nearly every committee
          buys from the same travel, shipping and software vendors, so this is not evidence
          of a relationship.</div>`:""}
      </div>`;
    }).join("");
});

// ---- toggles
["attributable","route","lead","labels"].forEach(k=>{
  const b=document.getElementById("t-"+k);
  b.addEventListener("click",()=>{
    show[k]=!show[k];
    b.setAttribute("aria-pressed",String(show[k]));
    draw();
  });
});
document.getElementById("t-theme").addEventListener("click",()=>{
  const root=document.documentElement;
  root.setAttribute("data-theme", root.getAttribute("data-theme")==="dark" ? "light" : "dark");
  draw();
});
svg.addEventListener("click", ev=>{
  if(ev.target===svg){ highlight=null;
    document.getElementById("selection").innerHTML='<p class="empty">Click a node in the graph.</p>';
    draw(); }
});

document.getElementById("warnings").innerHTML =
  DATA.warnings.map(w=>`<p>&middot; ${w}</p>`).join("") || '<p class="empty">None recorded.</p>';

function fit(){
  const r=document.getElementById("stage").getBoundingClientRect();
  W=Math.max(640,r.width); H=Math.max(520,r.height);
  draw();
}
window.addEventListener("resize",fit);
fit();
</script>
</body>
</html>
"""


def render(
    graph: ConnectionGraph,
    heading: str,
    subhead: str = "",
    intro: str = "",
    warnings: list[str] | None = None,
    suggest: tuple[str, str] | None = None,
) -> str:
    """One self-contained HTML page for a connection graph."""
    payload: dict[str, Any] = graph.to_dict()
    payload["warnings"] = warnings or []
    payload["suggest"] = list(suggest) if suggest else []

    counts = payload["counts"]
    default_intro = (
        f"{counts['nodes']} entities and {counts['edges']} disclosed relationships, "
        f"drawn from {len(payload['patterns_included'])} detection pattern(s). "
        f"{counts['attributable_edges']} carry a disclosed amount; "
        f"{counts['route_edges']} are connectivity only; "
        f"{counts['lead_edges']} are leads to check rather than findings."
    )

    return (
        _TEMPLATE
        .replace("__TITLE__", _escape(heading))
        .replace("__HEADING__", _escape(heading))
        .replace("__SUBHEAD__", _escape(subhead))
        .replace("__INTRO__", _escape(intro or default_intro))
        # json.dumps escapes the sequences that could close the script
        # element early; </script> inside a string literal would end it.
        .replace("__DATA__", json.dumps(payload).replace("</", "<\\/"))
    )


def _escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
