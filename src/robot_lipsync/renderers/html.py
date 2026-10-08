"""Dependency-free HTML preview built on the Mouth dot-matrix lips.

The drawing code lives in ``dotmatrix.js`` (shared with the tablet terminal),
with its tables in ``mouth_model.js`` and the OLED bitmaps in
``mouth_frames.js``. ``profile="oled"`` shows exactly the frames
firmware/esp32_oled draws on the 128x64 panel; ``profile="screen"`` is the same
mouth rebuilt continuously at twice the resolution for tablets and monitors.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from ..events import ArticulationEvent

PROFILES = ("screen", "oled")
PALETTES = ("red", "blue")


def dotmatrix_js() -> str:
    """mouth_model.js + mouth_frames.js + dotmatrix.js, ready to inline."""
    files = ("mouth_model.js", "mouth_frames.js", "dotmatrix.js")
    return "\n".join(resources.files(__package__).joinpath(name).read_text(encoding="utf-8") for name in files)


def render_html(
    events: list[ArticulationEvent],
    output: str | Path,
    *,
    title: str = "Robot LipSync",
    profile: str = "screen",
    palette: str = "red",
) -> Path:
    if profile not in PROFILES:
        raise ValueError(f"profile must be one of {PROFILES}")
    if palette not in PALETTES:
        raise ValueError(f"palette must be one of {PALETTES}")
    payload = json.dumps([event.to_dict() for event in events], ensure_ascii=False).replace("<", "\\u003c")
    template = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}
body{margin:0;background:#050203;color:#e8dfe1;font:15px ui-monospace,SFMono-Regular,Menlo,monospace;display:grid;place-items:center;min-height:100vh}
main{width:min(980px,96vw)}canvas{width:100%;height:auto;display:block;background:#050203;border:1px solid #2a1a1e}
.bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:14px 0}.bar input[type=range]{flex:1;min-width:160px}
button,select{background:#140a0d;color:inherit;border:1px solid #3a2a2e;padding:8px 14px;font:inherit;cursor:pointer}
#readout{color:#9a8a8e;min-height:2.5em}.tag{color:#6a5a5e;font-size:12px}
</style></head><body><main><canvas id="stage" width="960" height="480"></canvas>
<div class="bar"><button id="play">Play</button><input id="time" type="range" min="0" max="1000" value="0">
<select id="profile"><option value="screen">screen</option><option value="oled">oled</option></select>
<select id="palette"><option value="red">red</option><option value="blue">blue</option></select></div>
<div id="readout"></div><div class="tag">No audio or API key is required. oled = the exact frames firmware/esp32_oled draws; screen = the same Mouth mouth for tablets and monitors.</div></main>
<script>__DOTMATRIX__</script>
<script>const EVENTS=__EVENTS__;const cv=document.querySelector('#stage'),ctx=cv.getContext('2d'),slider=document.querySelector('#time'),readout=document.querySelector('#readout');
const prof=document.querySelector('#profile'),pal=document.querySelector('#palette');prof.value='__PROFILE__';pal.value='__PALETTE__';
let playing=false,started=0,offset=0,last=0;const end=Math.max(...EVENTS.map(e=>e.start_ms+e.duration_ms))+300;const track=DotLips.track(EVENTS);
function draw(ms){const a=track(ms),m=a.muscle;ctx.fillStyle='#050203';ctx.fillRect(0,0,cv.width,cv.height);
DotLips.draw(ctx,0,0,cv.width,a,{profile:prof.value,palette:pal.value,t:ms});
readout.textContent=`${a.label} frame=${a.frame} jaw=${m.jaw_open.toFixed(2)} separation=${m.lip_separation.toFixed(2)} width=${m.mouth_width.toFixed(2)} round=${m.lip_round.toFixed(2)} press=${m.lip_press.toFixed(2)}`;slider.value=Math.round(ms/end*1000)}
function tick(now){if(!playing)return;const ms=(now-started+offset)%end;draw(ms);last=now;requestAnimationFrame(tick)}
document.querySelector('#play').onclick=()=>{playing=!playing;if(playing){started=performance.now();last=started;requestAnimationFrame(tick)}else offset=Number(slider.value)/1000*end};
slider.oninput=()=>{offset=Number(slider.value)/1000*end;draw(offset)};prof.onchange=pal.onchange=()=>draw(offset);draw(0);</script></body></html>"""
    html = (
        template.replace("__TITLE__", title)
        .replace("__PROFILE__", profile)
        .replace("__PALETTE__", palette)
        .replace("__DOTMATRIX__", dotmatrix_js())
        .replace("__EVENTS__", payload)
    )
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path
