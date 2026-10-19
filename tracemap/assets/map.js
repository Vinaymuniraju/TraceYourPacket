(function () {
'use strict';

/* ---------- data and helpers ---------- */
const D = JSON.parse(document.getElementById('data').textContent);
const WORLD = JSON.parse(document.getElementById('world').textContent);
const $ = (s) => document.querySelector(s);
// Every string from the data goes in through textContent, never innerHTML.
const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const fmt = (v, d = 1) => (v == null ? '-' : v.toFixed(d));
const R_EARTH = 6371.0088;
const geoKm = (a, b) => d3.geoDistance(a, b) * R_EARTH;
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const stations = D.stations;
const hops = D.hops;
const lastStation = stations.length - 1;

/* ---------- svg scaffolding ---------- */
const svg = d3.select('#map');
const defs = svg.append('defs');
const og = defs.append('radialGradient').attr('id', 'ocean').attr('cx', '50%').attr('cy', '45%').attr('r', '75%');
og.append('stop').attr('offset', '0%').attr('stop-color', '#08122a');
og.append('stop').attr('offset', '100%').attr('stop-color', '#040913');
const glow = defs.append('filter').attr('id', 'glow').attr('x', '-10%').attr('y', '-10%').attr('width', '120%').attr('height', '120%');
glow.append('feGaussianBlur').attr('stdDeviation', 2).attr('result', 'b');
const fm = glow.append('feMerge');
fm.append('feMergeNode').attr('in', 'b');
fm.append('feMergeNode').attr('in', 'SourceGraphic');

const world = svg.append('g').attr('id', 'world');
const gSphere = world.append('path').attr('class', 'sphere');
const gGrat = world.append('path').attr('class', 'grat');
const gCountries = world.append('g');
const gBorder = world.append('path').attr('class', 'border');
const gCables = world.append('g').attr('filter', 'url(#glow)');
const gLandings = world.append('g');
const gRoute = world.append('g');
const overlay = svg.append('g').attr('id', 'overlay');
const gMarkers = overlay.append('g');
const gPackets = overlay.append('g');

/* ---------- projection, centred on the route so it never straddles the edge ---------- */
function circularMeanLon(lons) {
  let x = 0, y = 0;
  lons.forEach((l) => { x += Math.cos(l * Math.PI / 180); y += Math.sin(l * Math.PI / 180); });
  return Math.atan2(y, x) * 180 / Math.PI;
}
const lon0 = circularMeanLon(stations.map((s) => s.lon));
const projection = d3.geoNaturalEarth1().rotate([-lon0, 0]);
const geoPath = d3.geoPath(projection);
const countries = topojson.feature(WORLD, WORLD.objects.countries);
const borders = topojson.mesh(WORLD, WORLD.objects.countries, (a, b) => a !== b);

/* ---------- the route: densified polyline with cumulative km ---------- */
function densify(coords, stepDeg) {
  const out = [coords[0]];
  for (let i = 1; i < coords.length; i++) {
    const a = coords[i - 1], b = coords[i];
    const deg = d3.geoDistance(a, b) * 180 / Math.PI;
    const n = Math.max(1, Math.ceil(deg / stepDeg));
    const f = d3.geoInterpolate(a, b);
    for (let k = 1; k <= n; k++) out.push(f(k / n));
  }
  return out;
}
const R = (function buildRoute() {
  const pts = [], cum = [], segs = [], stationKm = [0];
  let km = 0;
  D.legs.forEach((leg, li) => {
    leg.segments.forEach((sg) => {
      const dp = densify(sg.coords, 1.2);
      const start = pts.length;
      dp.forEach((p) => {
        if (pts.length) km += geoKm(pts[pts.length - 1], p);
        pts.push(p); cum.push(km);
      });
      segs.push({ kind: sg.kind, name: sg.name, color: sg.color, start, end: pts.length - 1 });
    });
    stationKm[li + 1] = km;
  });
  return { pts, cum, segs, stationKm, total: km };
})();

function posAt(km) {
  const { pts, cum } = R;
  if (!pts.length) return [stations[0].lon, stations[0].lat];
  km = clamp(km, 0, R.total);
  let lo = 0, hi = cum.length - 1;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (cum[mid] < km) lo = mid + 1; else hi = mid; }
  if (lo === 0) return pts[0];
  const a = pts[lo - 1], b = pts[lo];
  const span = cum[lo] - cum[lo - 1];
  const f = span > 0 ? (km - cum[lo - 1]) / span : 1;
  if (Math.abs(b[0] - a[0]) > 180) return f < 0.5 ? a : b; // date line jump
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
}

/* ---------- layout (runs on load and resize) ---------- */
let W = 0, H = 0, T = d3.zoomIdentity;
const zoom = d3.zoom().scaleExtent([1, 120]).on('zoom', (e) => {
  T = e.transform;
  world.attr('transform', T);
  onZoom();
});
svg.call(zoom).on('dblclick.zoom', null);

const layers = { cables: true, borders: true, grat: true, landings: true, labels: true };

function layout() {
  const r = $('#stage').getBoundingClientRect();
  W = r.width; H = r.height;
  svg.attr('viewBox', `0 0 ${W} ${H}`);
  projection.fitExtent([[10, 10], [W - 10, H - 10]], { type: 'Sphere' });
  zoom.extent([[0, 0], [W, H]]).translateExtent([[0, 0], [W, H]]);

  gSphere.attr('d', geoPath({ type: 'Sphere' }));
  gGrat.attr('d', geoPath(d3.geoGraticule10()));
  gCountries.selectAll('path').data(countries.features).join('path').attr('class', 'country').attr('d', geoPath);
  gBorder.attr('d', geoPath(borders));

  const used = new Set(D.usedCables);
  gCables.selectAll('path').data(D.cables.features).join('path')
    .attr('class', (f) => 'cable' + (used.has(f.n) ? ' used' : ''))
    .attr('stroke', (f) => f.c)
    .attr('d', (f) => geoPath({ type: 'MultiLineString', coordinates: f.l }))
    .on('mouseenter', (e, f) => showTip(e, f.n, D.cables.real ? 'Submarine cable' : 'Illustrative corridor, not a real cable'))
    .on('mousemove', moveTip)
    .on('mouseleave', hideTip);

  gLandings.selectAll('circle').data(D.cables.landings).join('circle')
    .attr('cx', (p) => projection(p)[0]).attr('cy', (p) => projection(p)[1]);

  // route: one dim base stroke and one animated top stroke per segment
  gRoute.selectAll('*').remove();
  R.segs.forEach((s) => {
    const line = { type: 'LineString', coordinates: R.pts.slice(s.start, s.end + 1) };
    if (line.coordinates.length < 2) return;
    gRoute.append('path').attr('class', 'rt-base ' + s.kind).attr('d', geoPath(line));
    gRoute.append('path').attr('class', 'rt-top ' + s.kind).attr('d', geoPath(line));
  });

  onZoom();
}

function applyLayerVisibility() {
  gCables.style('display', layers.cables ? null : 'none');
  gBorder.style('display', layers.borders ? null : 'none');
  gGrat.style('display', layers.grat ? null : 'none');
  gLandings.style('display', layers.landings && layers.cables ? null : 'none');
  onZoom();
}

/* ---------- markers ---------- */
const stationHops = stations.map((_, i) => hops.filter((h) => h.station === i && h.located));
const reached = D.reached;
const isDest = (i) => reached && i === lastStation && i > 0;
const markers = stations.map((s, i) => {
  const g = gMarkers.append('g').attr('class', 'mk' + (i === 0 ? ' you' : '') + (isDest(i) ? ' dest' : ''));
  g.append('circle').attr('class', 'halo').attr('r', 11);
  if (i === 0) {
    g.append('rect').attr('class', 'core').attr('x', -6).attr('y', -6).attr('width', 12).attr('height', 12)
      .attr('transform', 'rotate(45)');
  } else {
    g.append('circle').attr('class', 'core').attr('r', 7.5);
    g.append('text').attr('class', 'badge').attr('y', 3.2).text(stationHops[i].length ? stationHops[i][0].ttl : '');
  }
  const ttls = stationHops[i].map((h) => h.ttl);
  const name = i === 0 ? (D.originGuess ? 'Start (first located hop)' : 'You') : s.label;
  g.append('text').attr('class', 'lbl').attr('x', 12).attr('y', -9)
    .text(i === 0 ? name : (ttls.length ? 'TTL ' + ttls.join(',') + ' · ' : '') + name);
  g.on('mouseenter', (e) => showStationTip(e, i)).on('mousemove', moveTip).on('mouseleave', hideTip)
    .on('click', () => { const h = stationHops[i][0]; if (h) playFrom(hops.indexOf(h)); });
  return g;
});

function placeMarkers() {
  const placed = [];
  markers.forEach((g, i) => {
    let q = T.apply(projection([stations[i].lon, stations[i].lat]));
    let n = 0;
    while (placed.some((p) => Math.hypot(p[0] - q[0], p[1] - q[1]) < 12) && n < 4) { q = [q[0] + 13, q[1] - 13]; n++; }
    placed.push(q);
    g.attr('transform', `translate(${q[0]},${q[1]})`);
    const important = i === 0 || isDest(i);
    const crowded = n > 0 && !important;
    const show = layers.labels && g.classed('active') || (layers.labels && !crowded && (important || T.k >= 2.4));
    g.select('.lbl').style('display', show ? null : 'none');
  });
}
function onZoom() {
  placeMarkers();
  gLandings.selectAll('circle').attr('r', 1.5 / T.k);
}

/* ---------- tooltip ---------- */
const tip = $('#tip');
function fillTip(title, lines) {
  tip.replaceChildren();
  tip.appendChild(el('b', null, title));
  lines.forEach((l) => tip.appendChild(el('div', 'mute', l)));
}
function showTip(e, title, line) { fillTip(title, line ? [line] : []); tip.hidden = false; moveTip(e); }
function moveTip(e) {
  const r = $('#stage').getBoundingClientRect();
  tip.style.left = clamp(e.clientX - r.left + 14, 4, r.width - 270) + 'px';
  tip.style.top = clamp(e.clientY - r.top + 14, 4, r.height - 90) + 'px';
}
function hideTip() { tip.hidden = true; }
function showStationTip(e, i) {
  const s = stations[i];
  const lines = [];
  if (i === 0) lines.push(D.originGuess ? 'Origin not given; starts at the first located hop' : 'Your location');
  stationHops[i].forEach((h) => lines.push(`TTL ${h.ttl}  ${h.ip}  ${h.rtt ? fmt(h.rtt.avg) + ' ms' : ''}`));
  showTip(e, i === 0 ? 'You' : s.label, []);
  lines.forEach((l) => tip.appendChild(el('div', 'mute mono', l)));
}

/* ---------- packets ---------- */
function makePacket() {
  const g = gPackets.append('g').style('display', 'none');
  const trail = d3.range(8).map(() => g.append('circle'));
  const head = g.append('circle').attr('class', 'pk-head').attr('r', 5.5);
  const lbl = g.append('text').attr('class', 'pk-lbl').attr('x', 10).attr('y', -9);
  return { g, trail, head, lbl };
}
const screenAt = (km) => T.apply(projection(posAt(km)));
function drawPacket(pk, km, dir, color, label) {
  const step = Math.max(R.total * 0.011, 8);
  pk.g.style('display', null);
  pk.trail.forEach((c, i) => {
    const q = screenAt(km - dir * (i + 1) * step);
    c.attr('cx', q[0]).attr('cy', q[1]).attr('r', 5 - i * 0.5).attr('fill', color).attr('opacity', 0.5 - i * 0.06);
  });
  const p = screenAt(km);
  pk.head.attr('cx', p[0]).attr('cy', p[1]).attr('fill', color);
  pk.lbl.attr('x', p[0] + 10).attr('y', p[1] - 9).attr('fill', color).text(label || '');
}
const hidePacket = (pk) => pk.g.style('display', 'none');
const probePk = makePacket();
const flowPool = d3.range(14).map(makePacket);
const burst = gPackets.append('circle').attr('class', 'burst').style('display', 'none');

/* ---------- animation state ---------- */
const SCALE = 14; // animation ms per real millisecond of one-way delay
let mode = 'probe', speed = 1, playing = !reduceMotion, loop = false;
const S = { i: 0, phase: 'out', t: 0, dur: 1000, km: 0, hop: hops[0], done: false };
let flow = [], flowTimer = 0, lastFrame = performance.now(), burstT = -1, burstAt = [0, 0];

const protoLabel = D.proto.name + (D.proto.port ? ' ' + D.proto.port : '');
function stationKm(h) { return R.stationKm[h.station] || 0; }
function oneWayMs(h) { return h.rtt ? h.rtt.avg / 2 : Math.max(stationKm(h) / 200, 1); }
function remainingTtl(h, km) {
  let passed = 0;
  hops.forEach((o) => { if (o.ttl < h.ttl && stationKm(o) <= km + 0.5) passed++; });
  return h.ttl - passed;
}

function startProbe(i) {
  const h = hops[i];
  S.i = i; S.hop = h; S.phase = 'out'; S.t = 0; S.done = false;
  S.km = stationKm(h);
  S.dur = S.km < 1 ? 500 : clamp(oneWayMs(h) * SCALE, 900, 6500);
  log(`TTL ${h.ttl}: ${D.proto.name} probe leaves toward ${D.target_ip}`);
  try { if (window.parent !== window) window.parent.postMessage({ tracemap: 'probe', i }, '*'); } catch (e) {}
}
window.addEventListener('message', (ev) => {
  const d = ev.data;
  if (ev.source !== window.parent || !d || d.tracemap !== 'play') return;
  if (Number.isInteger(d.i) && d.i >= 0 && d.i < hops.length) playFrom(d.i);
});
function playFrom(i) {
  mode = 'probe'; flow = []; flowPool.forEach(hidePacket);
  syncModeButtons();
  startProbe(i); playing = true; syncPlayButton();
  const st = stations[hops[i].station];
  flyTo(st);
}
function arrive(h) {
  burstAt = [h.station]; burstT = 0;
  if (h.lost) log(`TTL ${h.ttl}: no reply (all ${h.lost} probes lost)`, 'lost');
  else log(`TTL ${h.ttl} hit 0 at ${h.ip}${h.label ? ' (' + h.label + ')' : ''}`, 'drop');
}
function replied(h) {
  const last = D.reached && h === hops[hops.length - 1];
  log(`${last ? D.final_short : 'ICMP 11/0 time exceeded'} from ${h.ip} after ${fmt(h.rtt && h.rtt.avg)} ms`, 'back');
}
function nextProbe() {
  if (S.i + 1 < hops.length) { startProbe(S.i + 1); return; }
  S.done = true;
  log(D.reached ? `Destination reached after ${hops.length} probes` : 'Last probe finished; destination not reached', 'done');
  if (loop) { startProbe(0); } else { playing = false; syncPlayButton(); }
}

function step(dt) {
  if (mode === 'flow') {
    flowTimer += dt;
    const oneWay = clamp(oneWayMs(hops[hops.length - 1]) * SCALE, 1800, 9000);
    if (flowTimer > 520) {
      flowTimer = 0;
      flow.push({ t: 0, dir: flow.length % 3 === 2 ? -1 : 1, dur: oneWay });
    }
    flow.forEach((p) => { p.t += dt; });
    flow = flow.filter((p) => p.t < p.dur).slice(-flowPool.length);
    return;
  }
  if (S.done) return;
  S.t += dt;
  if (S.phase === 'out' && S.t >= S.dur) { S.phase = 'drop'; S.t = 0; arrive(S.hop); }
  else if (S.phase === 'drop' && S.t >= 650) { S.phase = S.hop.lost ? 'lost' : 'back'; S.t = 0; }
  else if (S.phase === 'back' && S.t >= S.dur) { S.phase = 'gap'; S.t = 0; replied(S.hop); }
  else if (S.phase === 'lost' && S.t >= 900) { S.phase = 'gap'; S.t = 0; }
  else if (S.phase === 'gap' && S.t >= 420) nextProbe();
}

/* ---------- per-frame drawing and HUD ---------- */
const hud = $('#hud');
hud.replaceChildren(el('h2', null, 'Packet inspector'));
const hudRows = {};
[['probe', 'Probe'], ['ttl', 'IP TTL'], ['type', 'Probe type'], ['where', 'Position'], ['rtt', 'Hop RTT']].forEach(([k, label]) => {
  const row = el('div', 'row');
  row.appendChild(el('span', 'mute', label));
  hudRows[k] = el('span', 'v mono', '-');
  row.appendChild(hudRows[k]);
  hud.appendChild(row);
});
const hudPhase = el('div', 'phase', '');
hud.appendChild(hudPhase);

function setPhase(cls, text) { hudPhase.className = 'phase ' + cls; hudPhase.textContent = text; }

function render() {
  const active = new Set();
  const seenKm = [];
  if (mode === 'flow') {
    hidePacket(probePk);
    flowPool.forEach(hidePacket);
    flow.forEach((p, i) => {
      const f = p.t / p.dur;
      const km = p.dir > 0 ? f * R.total : (1 - f) * R.total;
      drawPacket(flowPool[i], km, p.dir, p.dir > 0 ? '#8be9ff' : '#ffb86b', '');
    });
    hudRows.probe.textContent = 'continuous';
    hudRows.ttl.textContent = '-';
    hudRows.type.textContent = protoLabel;
    hudRows.where.textContent = `${Math.round(R.total)} km path`;
    hudRows.rtt.textContent = fmt(hops[hops.length - 1].rtt && hops[hops.length - 1].rtt.avg) + ' ms';
    setPhase('out', 'Blue packets go out, orange replies come back, all over the inferred path.');
  } else {
    const h = S.hop;
    let km = 0, color = '#8be9ff', dir = 1, label = '';
    if (S.phase === 'out') { km = S.km * clamp(S.t / S.dur, 0, 1); label = 'TTL ' + remainingTtl(h, km); }
    else if (S.phase === 'drop') { km = S.km; color = '#ff5d7a'; label = 'TTL 0'; }
    else if (S.phase === 'back') { km = S.km * (1 - clamp(S.t / S.dur, 0, 1)); color = '#ffb86b'; dir = -1; label = 'ICMP 11/0'; }
    else if (S.phase === 'lost') { km = S.km; color = '#ff5d7a'; label = 'no reply'; }
    else { km = S.phase === 'gap' && !h.lost ? 0 : S.km; }
    if (S.phase === 'gap') hidePacket(probePk); else drawPacket(probePk, km, dir, color, label);
    flowPool.forEach(hidePacket);
    seenKm.push(km);
    active.add(h.station);
    hudRows.probe.textContent = `${S.i + 1} / ${hops.length}`;
    hudRows.ttl.textContent = S.phase === 'out' ? String(remainingTtl(h, km)) : S.phase === 'back' ? 'ICMP' : S.phase === 'gap' ? '-' : '0';
    hudRows.type.textContent = S.phase === 'back' ? 'ICMP time exceeded' : protoLabel;
    hudRows.where.textContent = `${Math.round(km)} / ${Math.round(S.km)} km`;
    hudRows.rtt.textContent = fmt(h.rtt && h.rtt.avg) + ' ms';
    const where = `${h.ip || 'hop ' + h.ttl}${h.label ? ' (' + h.label + ')' : ''}`;
    if (S.done) setPhase('done', D.reached ? 'Destination reached. Press replay to run it again.' : 'Finished.');
    else if (S.phase === 'out') setPhase('out', `Outbound: TTL ${h.ttl} probe, each router subtracts 1.`);
    else if (S.phase === 'drop') setPhase('drop', `TTL reached 0 at ${where}. Packet dropped.`);
    else if (S.phase === 'back') setPhase('back', `ICMP error returns to you (RTT ${fmt(h.rtt && h.rtt.avg)} ms).`);
    else if (S.phase === 'lost') setPhase('lost', 'No ICMP reply came back for this TTL.');
    else setPhase('out', 'Next probe...');
  }

  markers.forEach((g, i) => {
    g.classed('active', active.has(i));
    g.classed('seen', seenKm.length ? R.stationKm[i] <= seenKm[0] + 0.5 : false);
  });

  if (burstT >= 0) {
    burstT += 16 * speed;
    const q = T.apply(projection([stations[burstAt[0]].lon, stations[burstAt[0]].lat]));
    const f = clamp(burstT / 650, 0, 1);
    burst.style('display', f >= 1 ? 'none' : null).attr('cx', q[0]).attr('cy', q[1])
      .attr('r', 6 + f * 26).attr('opacity', 1 - f).attr('stroke', S.hop && S.hop.lost ? '#ff5d7a' : '#ffd166');
    if (f >= 1) burstT = -1;
  }
  updateStrip();
  updateHopList();
}

function frame(now) {
  const dt = Math.min(64, now - lastFrame) * speed;
  lastFrame = now;
  if (playing) step(dt);
  render();
  requestAnimationFrame(frame);
}

/* ---------- log ---------- */
const logBox = $('#log');
function log(text, cls) {
  const line = el('div', 'line', text);
  logBox.querySelectorAll('.line').forEach((n) => n.classList.add('old'));
  logBox.appendChild(line);
  while (logBox.children.length > 5) logBox.removeChild(logBox.firstChild);
}

/* ---------- strip of probes ---------- */
const strip = $('#strip');
const stripBtns = hops.map((h, i) => {
  const b = el('button', null, String(h.ttl));
  b.title = `TTL ${h.ttl}: ${h.ip || 'no reply'}`;
  b.addEventListener('click', () => playFrom(i));
  strip.appendChild(b);
  return b;
});
function updateStrip() {
  stripBtns.forEach((b, i) => {
    const cur = mode === 'probe' && i === S.i && !S.done;
    const done = mode === 'probe' ? (i < S.i || (S.done && i <= S.i)) : false;
    b.className = (cur ? 'cur ' : '') + (done ? (hops[i].lost ? 'lost' : 'done') : '');
  });
}

/* ---------- side panel ---------- */
const panel = $('#panel');
const btn = (label, fn, cls) => { const b = el('button', 'b' + (cls ? ' ' + cls : ''), label); b.addEventListener('click', fn); return b; };
const bPlay = btn('Pause', () => { if (S.done && mode === 'probe') playFrom(0); else playing = !playing; syncPlayButton(); });
const bRestart = btn('Restart', () => playFrom(0));
const bNext = btn('Next probe', () => { if (mode === 'probe') playFrom(Math.min(S.i + 1, hops.length - 1)); });
const bFit = btn('Fit route', () => fitRoute(true));
const bWorld = btn('World', () => svg.transition().duration(700).call(zoom.transform, d3.zoomIdentity));
const bProbe = btn('Probe by probe', () => { mode = 'probe'; playFrom(0); }, 'on');
const bFlow = btn('Continuous flow', () => { mode = 'flow'; flow = []; playing = true; hidePacket(probePk); syncModeButtons(); syncPlayButton(); });
const spd = el('select', 'b');
spd.setAttribute('aria-label', 'Speed');
[['0.5', '0.5x'], ['1', '1x'], ['2', '2x'], ['4', '4x']].forEach(([v, t]) => { const o = el('option', null, t); o.value = v; if (v === '1') o.selected = true; spd.appendChild(o); });
spd.addEventListener('change', () => { speed = parseFloat(spd.value); });

function syncPlayButton() { bPlay.textContent = playing ? 'Pause' : (S.done && mode === 'probe' ? 'Replay' : 'Play'); }
function syncModeButtons() { bProbe.classList.toggle('on', mode === 'probe'); bFlow.classList.toggle('on', mode === 'flow'); }

const c1 = el('div', 'ctrl'); [bPlay, bRestart, bNext].forEach((b) => c1.appendChild(b));
const c2 = el('div', 'ctrl'); [bProbe, bFlow].forEach((b) => c2.appendChild(b));
const c3 = el('div', 'ctrl'); c3.appendChild(el('span', 'mute', 'Speed')); c3.appendChild(spd); c3.appendChild(bFit); c3.appendChild(bWorld);

const tg = el('div', 'toggles');
[['cables', 'Cables'], ['landings', 'Landings'], ['borders', 'Borders'], ['grat', 'Grid'], ['labels', 'Labels']].forEach(([k, t]) => {
  const l = el('label'); const c = el('input'); c.type = 'checkbox'; c.checked = true;
  c.addEventListener('change', () => { layers[k] = c.checked; applyLayerVisibility(); });
  l.appendChild(c); l.appendChild(document.createTextNode(t)); tg.appendChild(l);
});

const secA = el('div'); secA.appendChild(el('h2', null, 'Playback'));
[c1, c2, c3].forEach((c) => { c.style.marginBottom = '6px'; secA.appendChild(c); });
const secB = el('div'); secB.appendChild(el('h2', null, 'Layers')); secB.appendChild(tg);

const secC = el('div'); secC.appendChild(el('h2', null, 'Hops (click to replay)'));
const list = el('div', 'hoplist'); secC.appendChild(list);
const maxRtt = Math.max(1, ...hops.map((h) => (h.rtt ? h.rtt.avg : 0)));
const rows = hops.map((h, i) => {
  const r = el('div', 'hop' + (h.lost ? ' lost' : ''));
  r.appendChild(el('span', 'n mono', String(h.ttl)));
  const mid = el('div');
  mid.appendChild(el('div', 'ip mono', h.ip || '* * *'));
  mid.appendChild(el('div', 'loc', h.located ? h.label : (h.ip ? h.cls : 'no reply')));
  if (h.locSource === 'hostname' || h.locNote) {
    const n = el('div', 'hnote', h.locSource === 'hostname' ? 'Located from hostname' : 'Hostname suggests another city');
    n.title = h.locNote || ''; mid.appendChild(n);
  }
  if (h.check) {
    const w = el('div', 'wchk ' + h.check.level, (h.check.level === 'impossible' ? 'Location impossible' : 'Location doubtful') + ': RTT too low for the distance');
    w.title = h.check.msg; mid.appendChild(w);
  }
  r.appendChild(mid);
  r.appendChild(el('span', 'rt mono', h.rtt ? fmt(h.rtt.avg) + ' ms' : '-'));
  const bar = el('div', 'bar'); const fill = el('i'); fill.style.width = (h.rtt ? Math.max(2, 100 * h.rtt.avg / maxRtt) : 0) + '%';
  bar.appendChild(fill); r.appendChild(bar);
  r.addEventListener('click', () => playFrom(i));
  list.appendChild(r);
  return r;
});
let lastCur = -1;
function updateHopList() {
  const cur = mode === 'probe' ? S.i : -1;
  if (cur === lastCur) return;
  lastCur = cur;
  rows.forEach((r, i) => r.classList.toggle('cur', i === cur));
  if (cur >= 0) rows[cur].scrollIntoView({ block: 'nearest' });
}

const secD = el('div'); secD.appendChild(el('h2', null, 'Path the packets follow'));
const legLines = D.legs.map((l, i) => ({ l, i })).filter((x) => x.l.cables.length);
if (legLines.length) {
  const ul = el('ul', 'used');
  legLines.forEach(({ l }) => l.cables.forEach((c) => ul.appendChild(el('li', null, c))));
  secD.appendChild(ul);
} else {
  secD.appendChild(el('div', 'note', 'No leg of this route is long enough to need a submarine cable, or no cable data was loaded.'));
}
secD.appendChild(el('div', 'note', 'A traceroute does not say which cable a packet used. These paths are inferred from geography, and replies are drawn on the same path although the real return route can differ.'));

[secA, secB, secC, secD].forEach((s) => panel.appendChild(s));

/* ---------- title card, legend, credit ---------- */
const tc = $('#titlecard');
tc.appendChild(el('h1', null, 'Packet path to ' + (D.target || D.target_ip)));
tc.appendChild(el('div', 'sub mono', `${D.target_ip || ''} · ${D.proto.name} probes · ${D.reached ? 'destination reached' : 'destination not reached'}`));
const chips = el('div', 'chips');
const chip = (b, t, cls) => { const c = el('span', 'chip' + (cls ? ' ' + cls : '')); c.appendChild(el('b', null, b)); c.appendChild(document.createTextNode(' ' + t)); chips.appendChild(c); };
chip(String(hops.length), 'hops');
chip(Math.round(D.stats.totalKm).toLocaleString() + ' km', 'path');
chip(Math.round(D.stats.cableKm).toLocaleString() + ' km', 'on cables', D.stats.cableKm ? 'good' : '');
if (D.stats.rttMs != null) chip(fmt(D.stats.rttMs, 0) + ' ms', 'observed RTT');
if (D.stats.floorMs) chip(fmt(D.stats.floorMs, 0) + ' ms', 'fibre floor');
if (D.warnings) chip(String(D.warnings), D.warnings === 1 ? 'doubtful location' : 'doubtful locations', 'warn');
if (!D.cables.real) chip('illustrative cables', '', 'warn');
else if (D.cables.note) chip('cached cable data', '', 'warn');
tc.appendChild(chips);

const lg = $('#legend');
const row = (swClass, color, text) => { const d = el('div'); const s = el('span', swClass); s.style.borderColor = color; d.appendChild(s); d.appendChild(el('span', null, text)); lg.appendChild(d); };
const dotRow = (color, text) => { const d = el('div'); const s = el('span', 'dot'); s.style.background = color; d.appendChild(s); d.appendChild(el('span', null, text)); lg.appendChild(d); };
row('sw', '#e9fbff', 'Route over submarine cable');
row('sw dash', '#ffd166', 'Route over land (straight-line estimate)');
dotRow('#8be9ff', 'Probe going out');
dotRow('#ffb86b', 'ICMP reply coming back');
dotRow('#ff5d7a', 'TTL 0: dropped at this router');

const credit = $('#credit');
credit.textContent = (D.cables.attribution ? D.cables.attribution + '  ·  ' : '') + 'Basemap: Natural Earth via world-atlas';
if (!D.cables.real || D.cables.note) credit.classList.add('amber');
if (D.cables.note) credit.textContent = D.cables.note + '  ·  ' + credit.textContent;

/* ---------- view control ---------- */
function flyTo(st) {
  const p = projection([st.lon, st.lat]);
  const k = Math.max(T.k, 2.2);
  const t = d3.zoomIdentity.translate(W / 2 - k * p[0], H / 2 - k * p[1]).scale(k);
  svg.transition().duration(reduceMotion ? 0 : 700).call(zoom.transform, t);
}
function fitRoute(animate) {
  const pts = (R.pts.length ? R.pts : stations.map((s) => [s.lon, s.lat])).map((p) => projection(p));
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const bw = Math.max(x1 - x0, 40), bh = Math.max(y1 - y0, 40);
  const k = clamp(Math.min((W * 0.74) / bw, (H * 0.62) / bh), 1, 9);
  const t = d3.zoomIdentity.translate(W / 2 - k * (x0 + x1) / 2, H / 2 - k * (y0 + y1) / 2 + 20).scale(k);
  (animate ? svg.transition().duration(800) : svg).call(zoom.transform, t);
}

window.addEventListener('keydown', (e) => {
  if (e.target && /INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) return;
  if (e.code === 'Space') { e.preventDefault(); bPlay.click(); }
  if (e.code === 'ArrowRight') bNext.click();
  if (e.code === 'ArrowLeft' && mode === 'probe') playFrom(Math.max(S.i - 1, 0));
});
let resizeTimer = 0;
window.addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { layout(); fitRoute(false); }, 120); });

/* ---------- go ---------- */
layout();
fitRoute(false);
startProbe(0);
syncPlayButton();
syncModeButtons();
requestAnimationFrame(frame);
window.__tracemap = { S, R, D, get T() { return T; }, playFrom, setMode: (m) => { mode = m; flow = []; syncModeButtons(); }, step: (ms) => step(ms) };
})();
