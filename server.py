"""Custom-LLM WebSocket server for a Retell voice agent: after-hours intake for a small law firm.

Retell connects to wss://<host>/llm-websocket/{call_id}. We stream replies from any
OpenAI-compatible chat API, run tools (availability lookup, callback booking, warm transfer),
and log per-turn latency. Post-call analysis arrives at POST /webhook (HMAC-verified).
"""
import asyncio, hashlib, hmac, json, os, re, sqlite3, time
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException
from openai import AsyncOpenAI

LLM = AsyncOpenAI(base_url=os.environ.get("LLM_BASE_URL"), api_key=os.environ["LLM_API_KEY"])
MODEL = os.environ.get("LLM_MODEL", "gpt-4.1-mini")
TRANSFER_NUMBER = os.environ.get("TRANSFER_NUMBER", "")
RETELL_KEY = os.environ.get("RETELL_API_KEY", "")
DB = sqlite3.connect(os.environ.get("DB_PATH", "intake.db"), check_same_thread=False)
DB.execute("create table if not exists callbacks(call_id text, name text, phone text, matter text, slot text, ts real)")
DB.execute("create table if not exists turns(call_id text, response_id int, first_token_ms real, ts real)")

SYSTEM = """You answer the phone after hours for Hale & Ortiz, a small family-law firm.
Collect: caller name, callback number, matter type (divorce, custody, support, other), urgency.
Never give legal advice. If someone is in danger, tell them to call 911.
Offer a callback slot with check_availability, confirm it, then book_callback.
If the caller insists on a person or it's urgent, use transfer_to_human.
Keep turns short, one question at a time, spoken style."""

SLOTS = ["Tomorrow 9:30 AM", "Tomorrow 11:00 AM", "Tomorrow 2:15 PM", "Thursday 10:00 AM"]
TOOLS = [
    {"type": "function", "function": {"name": "check_availability", "description": "List open callback slots.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "book_callback", "description": "Book a callback slot.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "phone": {"type": "string"},
        "matter": {"type": "string"}, "slot": {"type": "string"}}, "required": ["name", "phone", "matter", "slot"]}}},
    {"type": "function", "function": {"name": "transfer_to_human", "description": "Transfer the call to the on-call attorney.",
        "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}}}},
]

app = FastAPI()

def to_messages(transcript):
    msgs = [{"role": "system", "content": SYSTEM}]
    for u in transcript:
        msgs.append({"role": "assistant" if u["role"] == "agent" else "user", "content": u["content"]})
    return msgs

def run_tool(call_id, name, args):
    if name == "check_availability":
        taken = {r[0] for r in DB.execute("select slot from callbacks")}
        return json.dumps([s for s in SLOTS if s not in taken])
    if name == "book_callback":
        DB.execute("insert into callbacks values (?,?,?,?,?,?)",
                   (call_id, args.get("name"), args.get("phone"), args.get("matter"), args.get("slot"), time.time()))
        DB.commit()
        return json.dumps({"booked": args.get("slot")})
    return json.dumps({"error": "unknown tool"})

async def respond(ws, call_id, response_id, transcript, cancelled):
    msgs = to_messages(transcript)
    t0 = time.perf_counter(); first = None
    for _ in range(3):  # allow up to two tool round-trips
        stream = await LLM.chat.completions.create(model=MODEL, messages=msgs, tools=TOOLS, stream=True)
        text, calls = "", {}
        async for chunk in stream:
            if cancelled():
                return
            d = chunk.choices[0].delta if chunk.choices else None
            if not d:
                continue
            if d.content:
                if first is None:
                    first = (time.perf_counter() - t0) * 1000
                text += d.content
                await ws.send_text(json.dumps({"response_type": "response", "response_id": response_id,
                                               "content": d.content, "content_complete": False}))
            for tc in d.tool_calls or []:
                c = calls.setdefault(tc.index, {"id": tc.id, "name": "", "args": ""})
                c["name"] += tc.function.name or ""; c["args"] += tc.function.arguments or ""
        if not calls:
            break
        msgs.append({"role": "assistant", "content": text or None, "tool_calls": [
            {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["args"]}} for c in calls.values()]})
        for c in calls.values():
            args = json.loads(c["args"] or "{}")
            if c["name"] == "transfer_to_human" and TRANSFER_NUMBER:
                await ws.send_text(json.dumps({"response_type": "response", "response_id": response_id,
                    "content": "One moment, I'm connecting you now.", "content_complete": True,
                    "transfer_number": TRANSFER_NUMBER}))
                return
            await ws.send_text(json.dumps({"response_type": "tool_call_invocation", "tool_call_id": c["id"],
                                           "name": c["name"], "arguments": c["args"]}))
            result = run_tool(call_id, c["name"], args)
            await ws.send_text(json.dumps({"response_type": "tool_call_result", "tool_call_id": c["id"], "content": result}))
            msgs.append({"role": "tool", "tool_call_id": c["id"], "content": result})
    await ws.send_text(json.dumps({"response_type": "response", "response_id": response_id,
                                   "content": "", "content_complete": True}))
    if first is not None:
        DB.execute("insert into turns values (?,?,?,?)", (call_id, response_id, first, time.time())); DB.commit()

@app.websocket("/llm-websocket/{call_id}")
async def llm_ws(ws: WebSocket, call_id: str):
    await ws.accept()
    await ws.send_text(json.dumps({"response_type": "config", "config": {"auto_reconnect": True, "call_details": False,
                                                                          "transcript_with_tool_calls": True}}))
    await ws.send_text(json.dumps({"response_type": "response", "response_id": 0, "content_complete": True,
        "content": "Hi, you've reached Hale and Ortiz after hours. I can take your details and set up a callback. What's your name?"}))
    latest = {"id": -1}; task = None
    try:
        while True:
            ev = json.loads(await ws.receive_text())
            kind = ev.get("interaction_type")
            if kind == "ping_pong":
                await ws.send_text(json.dumps({"response_type": "ping_pong", "timestamp": int(time.time() * 1000)}))
            elif kind in ("response_required", "reminder_required"):
                rid = ev["response_id"]; latest["id"] = rid
                if task and not task.done():
                    task.cancel()
                task = asyncio.create_task(respond(ws, call_id, rid, ev["transcript"], lambda r=rid: latest["id"] != r))
    except WebSocketDisconnect:
        if task:
            task.cancel()

def verify_signature(raw: str, header: str, now_ms: int | None = None) -> bool:
    # Retell: header "v={ms},d={hex}", digest = HMAC-SHA256(raw_body + ms, api_key); reject >5 min skew
    m = re.match(r"^v=(\d+),d=(.*)$", header or "")
    if not m:
        return False
    ts, digest = m.group(1), m.group(2)
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    if abs(now_ms - int(ts)) > 5 * 60 * 1000:
        return False
    expected = hmac.new(RETELL_KEY.encode(), (raw + ts).encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, digest)

@app.post("/webhook")
async def webhook(req: Request):
    body = await req.body()
    if RETELL_KEY and not verify_signature(body.decode(), req.headers.get("x-retell-signature", "")):
        raise HTTPException(401)
    ev = json.loads(body)
    if ev.get("event") == "call_analyzed":
        with open("analysis.jsonl", "a") as f:
            f.write(json.dumps(ev.get("call", {}).get("call_analysis", {})) + "\n")
    return {"ok": True}

@app.get("/stats")
def stats():
    rows = [r[0] for r in DB.execute("select first_token_ms from turns order by first_token_ms")]
    p = lambda q: rows[int(q * (len(rows) - 1))] if rows else None
    return {"turns": len(rows), "p50_first_token_ms": p(0.5), "p95_first_token_ms": p(0.95)}
