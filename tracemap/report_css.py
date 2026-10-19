"""Stylesheet for the HTML report (kept separate so report.py stays readable)."""

CSS = """
:root{--bg:#ffffff;--fg:#1f2328;--muted:#656d76;--card:#f6f8fa;--line:#d0d7de;
--fw:#1f5fbf;--bk:#c2570c;--ok:#1a7f37;--bad:#cf222e;--accent:#0969da;--hl:#fff8c5;}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#8d96a0;
--card:#161b22;--line:#30363d;--fw:#58a6ff;--bk:#ffa657;--ok:#3fb950;--bad:#ff7b72;
--accent:#58a6ff;--hl:#3b2e00;}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1180px;margin:0 auto;padding:28px 20px 80px}
h1{font-size:26px;margin:0 0 4px}
h2{font-size:20px;margin:44px 0 10px;padding-top:10px;border-top:1px solid var(--line)}
h3{font-size:15px;margin:0 0 6px}
p{margin:6px 0}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.92em}
.muted{color:var(--muted)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:16px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.stat b{display:block;font-size:20px}
.stat span{color:var(--muted);font-size:12.5px}
img.map{width:100%;height:auto;border:1px solid var(--line);border-radius:8px}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--card)}
svg text{font-family:system-ui,sans-serif;fill:var(--fg)}
svg .m{font-family:ui-monospace,Menlo,Consolas,monospace}
svg .halo{paint-order:stroke;stroke:var(--card);stroke-width:4px;stroke-linejoin:round}
svg .life{stroke:var(--line);stroke-width:1.5;stroke-dasharray:4 4}
svg .fw{stroke:var(--fw);stroke-width:2;fill:none}
svg .bk{stroke:var(--bk);stroke-width:2;fill:none}
svg .ok{stroke:var(--ok);stroke-width:2;fill:none}
svg .lost{stroke:var(--bad);stroke-width:2;fill:none;stroke-dasharray:6 4}
svg .box{fill:var(--bg);stroke:var(--line);stroke-width:1.5}
svg .box.dest{stroke:var(--ok);stroke-width:2.5}
svg .box.none{stroke:var(--bad);stroke-dasharray:4 3}
svg .ttl{fill:var(--bg);stroke:var(--fw);stroke-width:1.5}
svg .ttl0{fill:var(--bg);stroke:var(--bad);stroke-width:2}
.legend{display:flex;flex-wrap:wrap;gap:16px;margin:10px 0;font-size:13px}
.legend i{display:inline-block;width:26px;height:0;border-top:3px solid;vertical-align:middle;margin-right:6px}
table.hops{width:100%;border-collapse:collapse;font-size:13.5px}
table.hops th,table.hops td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
table.hops th{color:var(--muted);font-weight:600}
.bar{height:8px;background:var(--fw);border-radius:4px;min-width:2px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.card.dest{border-color:var(--ok)}
.card.none{border-style:dashed}
.badge{display:inline-block;font-size:11.5px;padding:1px 7px;border-radius:10px;
border:1px solid var(--line);margin:0 4px 4px 0;color:var(--muted)}
.card ol{margin:6px 0 6px 18px;padding:0;font-size:13.5px}
.card ul{margin:6px 0 0 18px;padding:0;font-size:13.5px}
.note-warn{color:var(--bad)}
.panels{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:14px}
.panel{border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--card)}
.panel>h3{margin:0;padding:9px 12px;background:var(--bg);border-bottom:1px solid var(--line)}
.layer{display:grid;grid-template-columns:92px 1fr;gap:8px;padding:8px 12px;
border-bottom:1px solid var(--line);font-size:13.5px}
.layer:last-child{border-bottom:0}
.layer b{color:var(--accent);font-size:12.5px}
.bits{display:grid;grid-template-columns:repeat(32,1fr);border:1px solid var(--line);
border-radius:6px;overflow:hidden;background:var(--bg);margin:6px 0 14px}
.bits div{padding:5px 6px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);
font-size:12px;min-height:44px}
.bits div small{display:block;color:var(--muted);font-size:10.5px}
.bits div.hl{background:var(--hl);font-weight:600}
.bits div.ill{font-style:italic}
.ruler{display:grid;grid-template-columns:repeat(4,1fr);font-size:10.5px;color:var(--muted);margin-top:8px}
.stack{display:flex;flex-direction:column;gap:0;max-width:560px;margin:8px 0}
.stack div{padding:7px 10px;border:1px solid var(--line);margin-top:-1px;font-size:13px;background:var(--bg)}
.stack div:nth-child(1){border-left:5px solid var(--fw)}
.stack div:nth-child(2){border-left:5px solid var(--bk)}
.stack div:nth-child(3){border-left:5px solid var(--ok)}
.stack div:nth-child(4){border-left:5px solid var(--muted)}
footer{margin-top:40px;color:var(--muted);font-size:13px}

.mapwrap{position:sticky;top:0;z-index:30;margin:10px 0 18px;padding:8px;background:var(--bg,#fff);
  border-bottom:1px solid var(--line);box-shadow:0 10px 24px rgba(0,0,0,.18)}
.mapwrap.unpinned{position:static;box-shadow:none}
.mapwrap iframe{display:block;width:100%;height:min(62vh,640px);min-height:380px;border:1px solid var(--line);
  border-radius:12px;background:#050912}
.maptools{display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap;
  font-size:12.5px;color:var(--muted,#667);margin-bottom:6px}
.maptools button{cursor:pointer;padding:3px 10px;border-radius:8px;border:1px solid var(--line);background:transparent;color:inherit}
.maptools button[aria-pressed=true]{background:rgba(124,156,255,.2)}
.hopcard,.hoprow{cursor:pointer;scroll-margin-top:calc(min(62vh,640px) + 70px)}
.hopcard:hover,.hoprow:hover{outline:1px solid var(--accent,#7c9cff)}
.hopcard.live{outline:2px solid #22d3ee;box-shadow:0 0 0 4px rgba(34,211,238,.15)}
.hoprow.live{background:rgba(34,211,238,.14)}
.cablenote{margin:6px 0;padding:6px 8px;border-radius:6px;background:rgba(34,211,238,.10);
  border-left:3px solid #22d3ee;font-size:13px}
@media(max-width:700px){.mapwrap{position:static}}
"""
