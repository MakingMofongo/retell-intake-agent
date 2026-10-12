"""Automated test caller: creates a Retell web call to our agent, joins the LiveKit room as the
'caller', speaks scripted lines (OpenAI TTS), records the agent's audio, then pulls Retell's
transcript + latency for the call. Usage: python test_caller.py [script_name]"""
import asyncio, json, os, sys, time, wave, io, urllib.request
import numpy as np
from livekit import rtc
from openai import OpenAI

RETELL = os.environ["RETELL_API_KEY"]; AGENT = os.environ["AGENT_ID"]
LK_URL = "wss://retell-ai-4ihahnq7.livekit.cloud"
SCRIPTS = {
  "book": ["Hi, this is Sam Patel.", "It's about custody of my daughter, not an emergency.",
           "My number is four one five, five five five, zero one nine eight.", "Tomorrow morning works.",
           "The nine thirty one is good.", "That's all, thanks."],
  "transfer": ["Hi, I need to talk to a lawyer right now, it's urgent.", "No, I want a real person please."],
}
SR = 24000

def api(path, body=None):
    req = urllib.request.Request("https://api.retellai.com" + path, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {RETELL}", "Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def tts(text):
    pcm = OpenAI().audio.speech.create(model="gpt-4o-mini-tts", voice="alloy", input=text, response_format="pcm").content
    return np.frombuffer(pcm, dtype=np.int16)  # 24 kHz mono

async def main(name):
    lines = [tts(t) for t in SCRIPTS[name]]
    call = api("/v3/create-web-call", {"agent_id": AGENT})
    room = rtc.Room(); agent_pcm = []; last_voice = [time.time()]
    @room.on("track_subscribed")
    def on_track(track, *_):
        async def pump():
            async for ev in rtc.AudioStream(track, sample_rate=SR, num_channels=1):
                a = np.frombuffer(ev.frame.data, dtype=np.int16); agent_pcm.append(a.copy())
                if np.abs(a).mean() > 300: last_voice[0] = time.time()
        asyncio.ensure_future(pump())
    await room.connect(LK_URL, call["access_token"])
    src = rtc.AudioSource(SR, 1); track = rtc.LocalAudioTrack.create_audio_track("mic", src)
    await room.local_participant.publish_track(track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
    silence = np.zeros(SR // 100, dtype=np.int16)
    async def send(samples):
        for i in range(0, len(samples), SR // 100):
            chunk = samples[i:i + SR // 100]
            if len(chunk) < SR // 100: chunk = np.pad(chunk, (0, SR // 100 - len(chunk)))
            await src.capture_frame(rtc.AudioFrame(chunk.tobytes(), SR, 1, SR // 100))
    async def wait_agent_done(min_wait=1.5, quiet=1.6, timeout=30):
        t0 = time.time()
        while time.time() - t0 < 12 and last_voice[0] < t0 + 0.3:   # wait for the agent to START speaking
            await send(silence)
        while time.time() - t0 < timeout and time.time() - last_voice[0] < quiet:  # then until it stops
            await send(silence)
        for _ in range(30): await send(silence)
    await wait_agent_done(min_wait=3)
    for s in lines:
        await send(s); await wait_agent_done()
    await asyncio.sleep(2); await room.disconnect()
    with wave.open(f"rec_{call['call_id']}.wav", "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(np.concatenate(agent_pcm).tobytes() if agent_pcm else b"")
    await asyncio.sleep(8)
    c = api(f"/v2/get-call/{call['call_id']}")
    print(json.dumps({"call_id": call["call_id"], "status": c.get("call_status"), "disconnection": c.get("disconnection_reason"),
                      "latency_e2e": (c.get("latency") or {}).get("e2e"), "transcript": c.get("transcript")}, indent=1))
asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "book"))
