"""Open a web page on this computer whenever Margin sends a cue.

    python examples/cue_opener.py octopus_video=https://vimeo.com/844129419

Run it next to `margin serve`. It reads the same event stream as the screens.
"""

import json
import sys
import time
import urllib.request
import webbrowser

SERVER = "http://localhost:8765"
pages = dict(arg.split("=", 1) for arg in sys.argv[1:])
seq = json.loads(urllib.request.urlopen(f"{SERVER}/api/screen").read())["seq"]
while True:
    try:
        reply = json.loads(urllib.request.urlopen(f"{SERVER}/api/poll?since={seq}&wait=20", timeout=30).read())
    except OSError:
        time.sleep(2)
        continue
    seq = reply["seq"]
    for event in reply.get("events", []):
        if event["kind"] == "cue" and event["data"]["name"] in pages:
            webbrowser.open(pages[event["data"]["name"]])
