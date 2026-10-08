"""Timing regressions with generated tones: no voices, keys, network or hardware."""
import array
import base64
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import wave

import pytest

from margin.alignment import reconcile, valid_alignment
from margin.speaker import Clip
from robot_lipsync.phonemes import TimedPhoneme
from robot_lipsync.planner import phonemes_to_articulation


def recording(runs=((.10, .40), (.75, 1.05)), seconds=1.3):
    rate = 16000
    samples = array.array('h', (round(6000 * math.sin(i * 2*math.pi*400/rate))
        if any(a <= i/rate < b for a,b in runs) else 0 for i in range(round(rate*seconds))))
    if sys.byteorder != 'little':
        samples.byteswap()
    output = io.BytesIO()
    with wave.open(output, 'wb') as f:
        f.setparams((1,2,rate,0,'NONE','not compressed'))
        f.writeframes(samples.tobytes())
    return output.getvalue()


def delayed_alignment():
    return dict(characters=list('你好。再见。'),
        character_start_times_seconds=[.25,.4,.55,.9,1.05,1.2],
        character_end_times_seconds=[.4,.55,.9,1.05,1.2,1.3])


@pytest.mark.parametrize('language,phones', [('zh',['ZH_BPM','ZH_A']),('en',['M','AA1']),('es',['ES_B','ES_A'])])
def test_short_phone_does_not_steal_time_from_next_phone(language, phones):
    events = phonemes_to_articulation('fast', [TimedPhoneme(phones[0],0,30,language),
        TimedPhoneme(phones[1],30,100,language)], minimum_readable_ms=70)
    assert events[0].duration_ms == 30
    assert events[1].start_ms == 30
    assert events[1].start_ms+events[1].duration_ms == 130


def test_short_final_does_not_animate_the_silent_gap():
    events=phonemes_to_articulation('gap', [TimedPhoneme('ZH_N',100,20,'zh'),
        TimedPhoneme('ZH_A',500,100,'zh')])
    assert events[0].start_ms+events[0].duration_ms == 120
    assert events[1].start_ms == 500


def test_opt_in_anticipation_is_ordered_and_does_not_overlap():
    phones=[TimedPhoneme(s,i*20,20,'zh') for i,s in enumerate(['ZH_BPM','ZH_A','ZH_N','ZH_BPM','ZH_A'])]
    events=phonemes_to_articulation('lead',phones,visual_lead_ms=42)
    assert all(a.start_ms+a.duration_ms <= b.start_ms for a,b in zip(events,events[1:]))
    assert max(e.start_ms+e.duration_ms for e in events) == 100


def test_clip_checks_delayed_provider_timing_against_audio(monkeypatch):
    monkeypatch.delenv('MARGIN_VISUAL_LEAD_MS',raising=False)
    original=delayed_alignment(); saved=copy.deepcopy(original)
    clip=Clip(recording(),'你好。再见。',mime='audio/wav',alignment=original)
    clip.make_timeline()
    assert clip.ready.is_set() and clip.timeline
    assert clip.alignment_status == 'waveform_phrase_edges'
    assert clip.seconds() == pytest.approx(1.3)
    assert clip.alignment['character_start_times_seconds'][0] == pytest.approx(.08)
    assert clip.alignment['character_end_times_seconds'][1] == pytest.approx(.42)
    assert clip.alignment['character_start_times_seconds'][3] == pytest.approx(.73)
    assert clip.speech_windows[1][1] == pytest.approx(1.07)
    assert all(a['start_ms']+a['duration_ms'] <= b['start_ms']+1e-7
               for a,b in zip(clip.timeline,clip.timeline[1:]))
    assert original == saved
    before=copy.deepcopy(clip.timeline);clip.make_timeline()
    assert clip.timeline == before


def test_silence_cannot_animate_provider_text():
    clip=Clip(recording(runs=()),'你好。',alignment=delayed_alignment())
    clip.make_timeline()
    assert clip.ready.is_set() and clip.timeline == []
    assert clip.speech_windows == [] and clip.alignment_status == 'silent'
    assert clip.audio


def test_ambiguous_pauses_do_not_move_provider_words():
    source=delayed_alignment()
    fixed,status=reconcile(source,[[.08,1.07]],1.3)
    assert status == 'provider_unverified'
    for i in [0,1,3,4]:
        assert fixed['character_start_times_seconds'][i] == source['character_start_times_seconds'][i]


def test_overlapping_character_and_separator_do_not_discard_valid_speech():
    source=delayed_alignment()
    source['character_end_times_seconds'][1]=1.1
    fixed,status=reconcile(source,[[.08,1.07]],1.3)
    assert status == 'provider_unverified' and valid_alignment(fixed)
    assert fixed['character_end_times_seconds'][1] == fixed['character_start_times_seconds'][3]


def test_cached_provider_audio_is_checked_without_resynthesis(tmp_path, monkeypatch):
    from margin.speech import ElevenLabsVoice
    monkeypatch.setenv('MARGIN_NATIVE_TIMING','1')
    monkeypatch.setenv('MARGIN_VOICE_CACHE_DIR',str(tmp_path))
    voice=object.__new__(ElevenLabsVoice)
    voice.voice_id,voice.model,voice.settings='fixture','fixture',{}
    voice._synthesize_uncached=lambda text: pytest.fail('cached audio must not be regenerated')
    text='你好。再见。'
    signature=json.dumps([voice.voice_id,voice.model,voice.settings,text],ensure_ascii=False)
    path=tmp_path/(hashlib.sha256(signature.encode()).hexdigest()+'.json')
    audio=recording()
    path.write_text(json.dumps({'audio':base64.b64encode(audio).decode(),
        'alignment':delayed_alignment()}))
    clip=voice._synthesize(text)
    assert clip.audio == audio and clip.alignment_status == 'waveform_phrase_edges'
    assert clip.alignment['character_start_times_seconds'][0] == pytest.approx(.08)


def test_speaker_endpoint_supplies_waveform_timing_to_browser():
    from margin.bus import Bus
    from margin.player import Player
    from margin.server import App, serve
    from margin.speech import SilentVoice
    clip=Clip(recording(),'你好。再见。',mime='audio/wav',alignment=delayed_alignment(),id='fixture')
    clip.make_timeline()
    bus=Bus()
    app=App(bus,Player(bus,SilentVoice()))
    app.hub._clips[clip.id]=clip
    server=serve(app,'127.0.0.1',0)
    base=f'http://127.0.0.1:{server.server_address[1]}'
    try:
        with urllib.request.urlopen(base+'/api/clip/fixture.json') as response:
            data=json.load(response)
        assert data['ready'] and data['alignment_status']=='waveform_phrase_edges'
        assert data['speech_windows']==clip.speech_windows and data['timeline']==clip.timeline
        with urllib.request.urlopen(base+'/api/clip/fixture') as response:
            assert response.read()==clip.audio
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-1,'later',None,True])
def test_malformed_times_are_rejected_without_crashing(value):
    a=delayed_alignment();a['character_start_times_seconds'][0]=value
    assert not valid_alignment(a)
    assert reconcile(a,[[.08,.42],[.73,1.07]],1.3)==(None,'unavailable')


def test_spoken_timestamps_beyond_audio_are_not_used():
    a=delayed_alignment();a['character_start_times_seconds']=[x+10 for x in a['character_start_times_seconds']]
    a['character_end_times_seconds']=[x+10 for x in a['character_end_times_seconds']]
    assert reconcile(a,[[.08,.42],[.73,1.07]],1.3)==(None,'outside_audio')


def test_screen_pose_is_rest_in_measured_pause():
    node=shutil.which('node')
    if not node:
        pytest.skip('Node is needed for the browser timeline unit test')
    root=Path(__file__).resolve().parents[1]/'src/robot_lipsync/renderers'
    script='''
    require(process.argv[1]+'/mouth_model.js'); require(process.argv[1]+'/dotmatrix.js');
    const e=[{start_ms:0,duration_ms:1000,viseme:'ZH_A',articulation:{},intensity:1}];
    const at=DotLips.track(e,{speechWindows:[[0,.2],[.8,1]]});
    const silent=DotLips.track(e,{speechWindows:[]});
    console.log(JSON.stringify({talking:at(100).muscle.jaw_open,
      gap:at(500).muscle,silent:silent(100).muscle,rest:DotLips.MODEL.targets.REST,
      gapLabel:at(500).label}));
    '''
    data=json.loads(subprocess.check_output([node,'-e',script,str(root)],text=True))
    assert data['talking'] > .4
    assert data['gap'] == data['rest']
    assert data['silent'] == data['rest']
    assert data['gapLabel'] == 'REST'
