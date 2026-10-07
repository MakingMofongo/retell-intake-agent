# retell-intake-agent
After-hours intake agent for a small law firm, built on Retell AI with a **custom LLM over WebSocket**, so the conversation logic runs on our own server.

## What's here
- `server.py`: FastAPI.
  - `/llm-websocket/{call_id}` speaks Retell's LLM WebSocket protocol: config, ping/pong, streamed `response` events, `tool_call_invocation`/`tool_call_result` bookkeeping, and `transfer_number` for call transfer.
  - `/webhook` receives `call_analyzed` events, verified per Retell's signature scheme (`v={ms},d=HMAC-SHA256(body+ms)`, 5-minute window).
  - `/stats` reports p50/p95 time-to-first-token.
- Tools: `check_availability`, `book_callback` (SQLite) and `transfer_to_human`.
- `test_caller.py`: an automated caller.
  - It creates a Retell web call, joins the LiveKit room as the caller, and speaks scripted turns with TTS.
  - It records the agent audio, then pulls Retell's transcript and latency for the call.
- `test_smoke.py`: protocol, tools and signature tests.
- Works with any OpenAI-compatible model (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`).

## Results (live Retell web calls, Oct 2026)
- The agent collects name, callback number and matter type, and offers only open slots.
- It turns down slots that are already booked, and books the callback.
- Retell's post-call analysis (matter type, urgency, booked slot) arrives on our webhook.
- End-to-end response latency measured by Retell: **p50 1.3 s**, p95 2.1 s (6 turns, gpt-4.1-mini).

## Notes
- Transfer over the custom-LLM socket is a cold transfer and only works on Retell-provisioned numbers. It doesn't fire from the dashboard web test.
- For local testing, expose the server with `cloudflared tunnel --url http://127.0.0.1:8711`.
