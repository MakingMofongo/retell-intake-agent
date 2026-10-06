# retell-intake-agent
After-hours intake agent for a small law firm, on Retell AI with a custom LLM over WebSocket.
- `server.py`: FastAPI. `/llm-websocket/{call_id}` speaks Retell's LLM WebSocket protocol (config, ping_pong, streamed responses, tool call invocation/result, cold transfer via `transfer_number`, Retell numbers only). `/webhook` takes post-call analysis. `/stats` reports p50/p95 time-to-first-token per turn.
- Any OpenAI-compatible model (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`).
- Tools: check_availability, book_callback (SQLite), transfer_to_human.
Signature check follows docs.retellai.com/features/secure-webhook (v={ms},d=HMAC(body+ms)). Transfer is cold only over the custom-LLM socket; it doesn't fire from the web test GUI. TODO: measure latency on 20 test calls.
