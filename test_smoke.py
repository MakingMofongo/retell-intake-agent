import json, os
os.environ.setdefault("LLM_API_KEY", "test"); os.environ["DB_PATH"] = ":memory:"
from fastapi.testclient import TestClient
import server
def test_opening_and_ping():
    c = TestClient(server.app)
    with c.websocket_connect("/llm-websocket/call_1") as ws:
        cfg = json.loads(ws.receive_text()); assert cfg["response_type"] == "config"
        hello = json.loads(ws.receive_text()); assert hello["response_id"] == 0 and hello["content_complete"]
        ws.send_text(json.dumps({"interaction_type": "ping_pong", "timestamp": 1}))
        assert json.loads(ws.receive_text())["response_type"] == "ping_pong"
def test_tools():
    assert "Tomorrow 9:30 AM" in server.run_tool("c", "check_availability", {})
    server.run_tool("c", "book_callback", {"name": "A", "phone": "1", "matter": "custody", "slot": "Tomorrow 9:30 AM"})
    assert "Tomorrow 9:30 AM" not in server.run_tool("c", "check_availability", {})

def test_signature():
    import hmac, hashlib
    server.RETELL_KEY = "k"; raw = '{"event":"call_analyzed"}'; ts = "1700000000000"
    d = hmac.new(b"k", (raw + ts).encode(), hashlib.sha256).hexdigest()
    assert server.verify_signature(raw, f"v={ts},d={d}", now_ms=1700000000000)
    assert not server.verify_signature(raw, f"v={ts},d={d}", now_ms=1700000000000 + 6*60*1000)
    assert not server.verify_signature(raw + " ", f"v={ts},d={d}", now_ms=1700000000000)
