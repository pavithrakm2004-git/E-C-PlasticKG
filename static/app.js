const COLORS = {Entity:"#2f7f86"};
const EDGE_COLORS = {Supports:"#2f8f5b", Challenges:"#c4452f", Refines:"#6a5acd", Inconclusive:"#d98e1f"};
let network, nodesDS, edgesDS, current;

const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

fetch("/api/keywords").then(r => r.json()).then(groups => {
  $("#chips").innerHTML = Object.entries(groups).map(([cat, kws]) =>
    `<div class="chip-group"><b>${esc(cat)}</b>${kws.map(k =>
      `<button type="button" class="chip" data-k="${esc(k)}">${esc(k)}</button>`).join("")}</div>`).join("");
  $("#chips").addEventListener("click", e => {
    const k = e.target.dataset.k; if (k) { $("#q").value = k; run(k); }
  });
});
$("#searchForm").addEventListener("submit", e => { e.preventDefault(); run($("#q").value); });
  $("#legend").innerHTML = [["Entity",COLORS.Entity]]
  .map(([l,c]) => `<li><i style="background:${c}"></i>${l}</li>`).join("");

async function run(q) {
  q = q.trim(); if (!q) return;
  $("#summary").textContent = "Building graph...";
  const res = await fetch("/api/search?q=" + encodeURIComponent(q));
  const g = await res.json();
  if (!res.ok) { $("#summary").textContent = g.error; return; }
  current = g; render(g);
}

function nodeStyle(n) {
  const base = {id:n.id, label:n.label, title:n.type, _n:n, font:{face:"IBM Plex Sans", size:13}};
  if (n.type === "Entity") return {...base, shape:"ellipse", color:{background:COLORS.Entity, border:"#1d5a60"},
      font:{color:"#fff", size:n.data.is_query ? 18 : 14, face:"IBM Plex Sans"}, borderWidth:n.data.is_query ? 4 : 1};
  return {...base, hidden:true};
}

function render(g) {
  const s = g.stats;
  $("#summary").innerHTML = `<b>${esc(g.keyword)}</b>: ${s.claims} claims from ${s.abstracts} abstracts, ` +
    `${s.entities} entities. Uncertainty U1 ${s.uncertainty.U1} / U2 ${s.uncertainty.U2} / U3 ${s.uncertainty.U3}.`;
  if (!s.claims) { $("#summary").innerHTML += " No matching claims found."; }
  $("#filters").hidden = false;
  const graphNodes = g.nodes.filter(n => n.type === "Entity");
  const entityIds = new Set(graphNodes.map(n => n.id));
  const graphEdges = g.edges.filter(e => entityIds.has(e.from) && entityIds.has(e.to));
  nodesDS = new vis.DataSet(graphNodes.map(nodeStyle));
  edgesDS = new vis.DataSet(graphEdges.map((e,i) => ({id:i, from:e.from, to:e.to, label:e.label, _e:e,
    arrows:"to", font:{color:getComputedStyle(document.body).color, size:12, align:"middle", strokeWidth:3,
      strokeColor:getComputedStyle(document.body).backgroundColor},
    color:{color:EDGE_COLORS[e.label] || "#7a9296"}, width:EDGE_COLORS[e.label] ? 3 : 1,
    dashes: e.label === "From Finding"})));
  network = new vis.Network($("#graph"), {nodes:nodesDS, edges:edgesDS}, {
    physics:{solver:"forceAtlas2Based", forceAtlas2Based:{gravitationalConstant:-70, springLength:130}, stabilization:{iterations:200}},
    interaction:{hover:true}});
  network.on("click", p => {
    if (p.nodes.length) showNode(nodesDS.get(p.nodes[0])._n);
    else if (p.edges.length) showEdgeTriple(edgesDS.get(p.edges[0])._e);
  });
  applyFilters();
}

function describeNode(n) {
  if (!n) return "Unknown node";
  const d = n.data || {};
  if (n.type === "Entity") return "Entity (" + d.entity_type + "): " + n.label;
  if (n.type === "Claim") return "Claim [" + d.abstract_id + "]: " + d.full_text;
  if (n.type === "Evidence") return "Evidence [" + d.abstract_id + "]: " + d.passage;
  if (n.type === "Uncertainty") return "Uncertainty: " + d.level;
  return n.type + ": " + n.label;
}

function renderTriples(g, hidden = new Set()) {
  const visible = g.nodes.filter(n => n.type === "Claim" && !hidden.has(n.id) &&
    n.data.sop_subject && n.data.sop_object);
  $("#tripleCount").textContent = visible.length + " triples";
  $("#triples tbody").innerHTML = visible.length
    ? visible.map(n => `<tr data-claim="${esc(n.id)}"><td>` + esc(n.data.sop_subject) +
        "</td><td class=\"triple-relation\">" + esc(n.data.sop_predicate) +
        "</td><td>" + esc(n.data.sop_object) + "</td></tr>").join("")
    : "<tr><td colspan=\"3\" class=\"muted\">No triples match the current filters.</td></tr>";
}

function showEdgeTriple(e) {
  const byId = new Map(current.nodes.map(n => [n.id, n]));
  const claim = byId.get(e.data?.claim_id);
  showTripleDetails(e.from, e.label, e.to, claim);
}

function showTripleDetails(from, relation, to, claim) {
  const byId = new Map(current.nodes.map(n => [n.id, n]));
  const evidence = claim && byId.get("EV_" + claim.id);
  const endpoint = value => {
    const node = byId.get(value);
    return node ? describeNode(node) : String(value || "");
  };
  $("#detail").innerHTML = "<h2>Graph triple</h2><dl class=\"triple-detail\">" +
    "<dt>Head</dt><dd>" + esc(endpoint(from)) + "</dd>" +
    "<dt>Relation</dt><dd><b>" + esc(relation) + "</b></dd>" +
    "<dt>Tail</dt><dd>" + esc(endpoint(to)) + "</dd></dl>" +
    (claim ? "<h3>Claim</h3><p class=\"ctx\">" + esc(claim.data.full_text) + "</p>" : "") +
    (evidence ? "<h3>Evidence</h3><p class=\"ctx\">" + esc(evidence.data.passage) + "</p>" : "");
}

$("#triples tbody").addEventListener("click", e => {
  const row = e.target.closest("tr[data-claim]");
  if (!row || !current) return;
  const claim = current.nodes.find(n => n.id === row.dataset.claim);
  if (claim) showTripleDetails(claim.data.sop_subject, claim.data.sop_predicate,
    claim.data.sop_object, claim);
});

function applyFilters() {
  if (!current) return;
  const on = new Set([...document.querySelectorAll("[data-u]")].filter(c => c.checked).map(c => c.dataset.u));
  const ev = $("#showEv").checked, hide = new Set();
  current.nodes.forEach(n => {
    if (n.type === "Uncertainty" && !on.has(n.data.level)) { hide.add(n.id); hide.add(n.id.replace("U_","")); hide.add(n.id.replace("U_","EV_")); }
    if (n.type === "Evidence" && !ev) hide.add(n.id);
  });
  // a claim is hidden only if its own uncertainty level is filtered out
  const claimHidden = id => hide.has(id) && current.nodes.find(n => n.id === "U_" + id && !on.has(n.data.level));
  nodesDS.update(current.nodes.filter(n => n.type === "Entity").map(n => ({id:n.id, hidden:false})));
  renderTriples(current, hide);
}
document.querySelector("#filters").addEventListener("change", applyFilters);

function showNode(n) {
  const d = n.data; let h = `<h2>${esc(n.type)}</h2><p><b>${esc(n.label)}</b></p>`;
  if (n.type === "Entity") h += `<dl class="kv"><dt>Type</dt><dd>${esc(d.entity_type)}</dd></dl>`;
  if (n.type === "Claim") {
    h += `<p class="ctx">${esc(d.full_text)}</p><h3>Scope</h3><dl class="kv">` +
      (Object.entries(d.scope).filter(([k]) => k !== "inherited_from_abstract").map(([k,v]) =>
        `<dt>${esc(k.replace("_"," "))}</dt><dd>${esc(v)}${(d.scope.inherited_from_abstract||[]).includes(k) ? " <span class='muted'>(from elsewhere in abstract)</span>" : ""}</dd>`).join("") || "<dd class='muted'>None stated</dd>") +
      `</dl><dl class="kv"><dt>Polarity</dt><dd>${esc(d.polarity)}</dd><dt>Source</dt><dd>${esc(d.abstract_id)}</dd></dl>`;
  }
  if (n.type === "Evidence") {
    const c = d.context; h += `<p class="muted">${esc(d.abstract_id)}: ${esc(d.abstract_title)}</p><p class="ctx">` +
      esc(c.slice(0,d.start)) + `<mark>${esc(c.slice(d.start,d.end))}</mark>` + esc(c.slice(d.end)) + `</p>`;
  }
  if (n.type === "Uncertainty") h += `<p><span class="badge" style="background:${COLORS[d.level]}">${esc(d.level)}</span></p><p>${esc(d.description)}</p>` +
      (d.cue ? `<p class="muted">Triggered by: "${esc(d.cue)}"</p>` : "");
  $("#detail").innerHTML = h;
}
function showEdge(e) {
  $("#detail").innerHTML = `<h2>Relationship</h2><p><b>${esc(e.label)}</b></p><p class="muted">${esc(e.from)} to ${esc(e.to)}</p>`;
}
