import json
import pytest
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError
import threading
import time

from jayu import dashboard
from jayu.paths import RuntimePaths

# We can run the dashboard server on a test port and perform HTTP requests to verify the endpoints.
@pytest.fixture(scope="module")
def test_server(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("dashboard_test")
    project_root = tmp_path / "project"
    runs_dir = project_root / "runs"
    state_dir = project_root / "state"
    signals_dir = project_root / "signals"
    
    runs_dir.mkdir(parents=True)
    state_dir.mkdir(parents=True)
    signals_dir.mkdir(parents=True)
    
    # Write empty config and today_signals
    config_file = project_root / "config.json"
    config_file.write_text(json.dumps({
        "runtime_paths": {
            "state_dir": str(state_dir),
            "signals_dir": str(signals_dir),
            "runs_dir": str(runs_dir)
        }
    }), encoding="utf-8")
    
    paths = RuntimePaths.from_root(
        project_root,
        config_file=config_file,
        state_dir=state_dir,
        signals_dir=signals_dir,
        runs_dir=runs_dir
    )
    
    # Start server in a background thread
    port = 9088
    server_thread = threading.Thread(
        target=dashboard.serve_dashboard,
        args=(paths,),
        kwargs={"host": "127.0.0.1", "port": port, "open_browser": False},
        daemon=True
    )
    server_thread.start()
    
    # Wait for server to start
    time.sleep(1.0)
    yield f"http://127.0.0.1:{port}"

def test_get_endpoints(test_server):
    # 1. Test /api/v1/system/migrations
    req = Request(f"{test_server}/api/v1/system/migrations")
    with urlopen(req) as res:
        data = json.loads(res.read().decode("utf-8"))
        assert "reports" in data

    # 2. Test /api/v1/ops-datamart/trends
    req = Request(f"{test_server}/api/v1/ops-datamart/trends")
    with urlopen(req) as res:
        data = json.loads(res.read().decode("utf-8"))
        assert "run_count" in data
        assert "success_rate" in data

    # 3. Test /api/v1/routines
    req = Request(f"{test_server}/api/v1/routines")
    with urlopen(req) as res:
        data = json.loads(res.read().decode("utf-8"))
        assert "routines" in data
        assert "pre_market" in data["routines"]

    # 4. Test /api/v1/provider-sla
    req = Request(f"{test_server}/api/v1/provider-sla")
    with urlopen(req) as res:
        data = json.loads(res.read().decode("utf-8"))
        assert "sla_compliant" in data

    # 5. Test /api/v1/tax-lots
    req = Request(f"{test_server}/api/v1/tax-lots")
    with urlopen(req) as res:
        data = json.loads(res.read().decode("utf-8"))
        assert "lots" in data

    # 6. Test /api/v1/approvals
    req = Request(f"{test_server}/api/v1/approvals")
    with urlopen(req) as res:
        data = json.loads(res.read().decode("utf-8"))
        assert "history" in data

def test_post_endpoints(test_server):
    # Set permission mode to admin first to allow recording approvals
    perm_req = Request(
        f"{test_server}/api/v1/permission-mode",
        data=json.dumps({"mode": "admin"}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urlopen(perm_req) as res:
        perm_data = json.loads(res.read().decode("utf-8"))
        assert perm_data["status"] == "success"

    # Test POST /api/v1/approvals
    payload = {
        "run_id": "test_run",
        "ticker": "AAPL",
        "action": "buy",
        "rec_verdict": "approved",
        "user_decision": "approve",
        "rationale": "Strong earnings beat"
    }
    
    req = Request(
        f"{test_server}/api/v1/approvals",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    
    with urlopen(req) as res:
        data = json.loads(res.read().decode("utf-8"))
        assert data["status"] == "success"
        assert data["entry"]["ticker"] == "AAPL"
        assert data["entry"]["user_decision"] == "approve"
