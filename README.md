# retell-intake-agent
After-hours intake agent for a small law firm, on Retell AI with a custom LLM over WebSocket.
- `server.py`: FastAPI. `/llm-websocket/{call_id}` speaks Retell's LLM WebSocket protocol (config, ping_pong, streamed responses, tool call invocation/result, warm transfer). `/webhook` takes post-call analysis. `/stats` reports p50/p95 time-to-first-token per turn.
- Any OpenAI-compatible model (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`).
- Tools: check_availability, book_callback (SQLite), transfer_to_human.
TODO before going live: verify the webhook signature format and the response-event transfer field against Retell's docs; measure latency on 20 test calls.
