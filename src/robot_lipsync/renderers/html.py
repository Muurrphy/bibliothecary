"""Dependency-free Canvas renderer for a five-minute, no-hardware demo."""

from __future__ import annotations

import json
from pathlib import Path

from ..events import ArticulationEvent


def render_html(events: list[ArticulationEvent], output: str | Path, *, title: str = "Robot LipSync") -> Path:
    payload = json.dumps([event.to_dict() for event in events], ensure_ascii=False).replace("<", "\\u003c")
    template = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#05070c;color:#dce8ff;font:15px ui-monospace,SFMono-Regular,Menlo,monospace;display:grid;place-items:center;min-height:100vh}
main{width:min(980px,96vw)}canvas{width:100%;height:auto;border:1px solid #16274a;border-radius:18px;background:radial-gradient(circle at 50% 42%,#081a3b,#02040a 70%);box-shadow:0 0 50px #004cff28}.bar{display:flex;gap:12px;align-items:center;margin:14px 0}.bar button{background:#0b5cff;color:white;border:0;padding:10px 18px;border-radius:999px;font:inherit;cursor:pointer}.bar input{flex:1}#readout{color:#74a7ff;min-height:2.5em}.tag{color:#6682ae;font-size:12px}
</style></head><body><main><canvas id="stage" width="960" height="420"></canvas><div class="bar"><button id="play">Play</button><input id="time" type="range" min="0" max="1000" value="0"></div><div id="readout"></div><div class="tag">No audio or API key is required. This preview renders device-independent articulation events.</div></main>
<script>const EVENTS=__EVENTS__;const canvas=document.querySelector('#stage'),ctx=canvas.getContext('2d'),slider=document.querySelector('#time'),readout=document.querySelector('#readout');let playing=false,started=0,offset=0;const end=Math.max(...EVENTS.map(e=>e.start_ms+e.duration_ms));
function lerp(a,b,t){return a+(b-a)*t}function eventAt(ms){let hit=EVENTS[0];for(const e of EVENTS){if(e.start_ms<=ms)hit=e;else break}return hit}function draw(ms){const e=eventAt(ms),a=e.articulation,round=a.lip_round,open=a.lip_separation;ctx.clearRect(0,0,960,420);const cx=480+a.asymmetry*26,cy=205;const hw=(175+a.mouth_width*105)*(1-round*.44),gap=5+open*98,top=26+a.lip_press*10+round*8,bottom=34+open*16+round*10;ctx.save();ctx.shadowColor='#1267ff';ctx.shadowBlur=18+e.intensity*18;ctx.fillStyle='#075dff';ctx.beginPath();ctx.moveTo(cx-hw,cy-gap*.22);ctx.bezierCurveTo(cx-hw*.68,cy-top,cx-hw*.23,cy-top*1.55,cx,cy-top*.82);ctx.bezierCurveTo(cx+hw*.23,cy-top*1.55,cx+hw*.68,cy-top,cx+hw,cy-gap*.22);ctx.bezierCurveTo(cx+hw*.68,cy-gap*.45,cx+hw*.28,cy-gap*.32,cx,cy-gap*.22);ctx.bezierCurveTo(cx-hw*.28,cy-gap*.32,cx-hw*.68,cy-gap*.45,cx-hw,cy-gap*.22);ctx.fill();ctx.beginPath();ctx.moveTo(cx-hw,cy+gap*.22);ctx.bezierCurveTo(cx-hw*.62,cy+gap*.44,cx-hw*.25,cy+gap*.30,cx,cy+gap*.20);ctx.bezierCurveTo(cx+hw*.25,cy+gap*.30,cx+hw*.62,cy+gap*.44,cx+hw,cy+gap*.22);ctx.bezierCurveTo(cx+hw*.62,cy+bottom*1.35,cx+hw*.25,cy+bottom*1.62,cx,cy+bottom*1.62);ctx.bezierCurveTo(cx-hw*.25,cy+bottom*1.62,cx-hw*.62,cy+bottom*1.35,cx-hw,cy+gap*.22);ctx.fill();ctx.restore();ctx.fillStyle='#89b4ff';ctx.font='15px ui-monospace';ctx.fillText('streaming articulation / physical-clock ready',28,34);readout.textContent=`${e.viseme}  jaw=${a.jaw_open.toFixed(2)} separation=${a.lip_separation.toFixed(2)} width=${a.mouth_width.toFixed(2)} round=${a.lip_round.toFixed(2)} press=${a.lip_press.toFixed(2)}`;slider.value=Math.round(ms/end*1000)}function tick(now){if(!playing)return;const ms=(now-started+offset)%end;draw(ms);requestAnimationFrame(tick)}document.querySelector('#play').onclick=()=>{playing=!playing;if(playing){started=performance.now();requestAnimationFrame(tick)}else offset=Number(slider.value)/1000*end};slider.oninput=()=>{offset=Number(slider.value)/1000*end;draw(offset)};draw(0);</script></body></html>"""
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template.replace("__TITLE__", title).replace("__EVENTS__", payload), encoding="utf-8")
    return path
