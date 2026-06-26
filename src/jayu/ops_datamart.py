from __future__ import annotations

import sqlite3
import json
from pathlib import Path
import logging
from typing import Any
from datetime import datetime

logger = logging.getLogger(__name__)

def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. runs table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        timestamp TEXT,
        execution_status TEXT,
        safety_decision TEXT,
        failure_code TEXT,
        score REAL
    )
    """)
    
    # 2. signals table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT,
        ticker TEXT,
        action TEXT,
        strategy TEXT,
        score REAL,
        status TEXT,
        data_verified INTEGER,
        FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
    )
    """)
    
    # 3. risk_verdicts table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS risk_verdicts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT,
        ticker TEXT,
        rule_code TEXT,
        verdict TEXT,
        message TEXT,
        FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
    )
    """)
    
    # 4. account_attributions table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS account_attributions (
        run_id TEXT PRIMARY KEY,
        timestamp TEXT,
        price_effect REAL,
        fx_effect REAL,
        holdings_effect REAL,
        cash_effect REAL,
        FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
    )
    """)
    
    # 5. stock_lifecycles table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stock_lifecycles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT,
        ticker TEXT,
        current_state TEXT,
        duration_days INTEGER,
        FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
    )
    """)
    
    # 6. failure_patterns table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS failure_patterns (
        run_id TEXT PRIMARY KEY,
        repeated_code_count INTEGER,
        active_streak_count INTEGER,
        top_code TEXT,
        FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
    )
    """)
    
    conn.commit()
    conn.close()

def insert_run_data(db_path: Path, paths: Any, run_id: str) -> bool:
    run_dir = paths.runs_dir / run_id
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        return False
        
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load manifest for run {run_id}: {e}")
        return False
        
    execution_status = manifest.get("execution_status", "unknown")
    safety_decision = manifest.get("safety_decision", "unknown")
    failure_code = manifest.get("failure_code", "NONE")
    score = manifest.get("health", {}).get("score", 100.0)
    
    # Extract timestamp from run_id (format: YYYYMMDD_HHMMSS_...)
    timestamp = run_id[:15] if len(run_id) >= 15 else datetime.now().strftime("%Y%m%d_%H%M%S")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Upsert run
    cursor.execute("""
    INSERT INTO runs (run_id, timestamp, execution_status, safety_decision, failure_code, score)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(run_id) DO UPDATE SET
        execution_status = excluded.execution_status,
        safety_decision = excluded.safety_decision,
        failure_code = excluded.failure_code,
        score = excluded.score
    """, (run_id, timestamp, execution_status, safety_decision, failure_code, score))
    
    # Clean old related data before inserting fresh
    cursor.execute("DELETE FROM signals WHERE run_id = ?", (run_id,))
    cursor.execute("DELETE FROM risk_verdicts WHERE run_id = ?", (run_id,))
    cursor.execute("DELETE FROM account_attributions WHERE run_id = ?", (run_id,))
    cursor.execute("DELETE FROM stock_lifecycles WHERE run_id = ?", (run_id,))
    cursor.execute("DELETE FROM failure_patterns WHERE run_id = ?", (run_id,))
    
    # 2. Insert signals
    signals_path = run_dir / "today_signals.json"
    if signals_path.exists():
        try:
            with open(signals_path, "r", encoding="utf-8") as f:
                sig_data = json.load(f)
            signals_list = sig_data.get("signals", []) if isinstance(sig_data, dict) else (sig_data if isinstance(sig_data, list) else [])
            for sig in signals_list:
                ticker = sig.get("ticker", "UNKNOWN")
                action = sig.get("action", "hold")
                strategy = sig.get("strategy", "unknown")
                sig_score = sig.get("score", 0.0)
                sig_status = sig.get("status", "not_evaluated")
                data_verified = 1 if sig.get("data_verified") else 0
                
                cursor.execute("""
                INSERT INTO signals (run_id, ticker, action, strategy, score, status, data_verified)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (run_id, ticker, action, strategy, sig_score, sig_status, data_verified))
        except Exception as e:
            logger.error(f"Failed to insert signals for run {run_id}: {e}")
            
    # 3. Insert risk verdicts
    risk_path = run_dir / "signals_risk.json"
    if risk_path.exists():
        try:
            with open(risk_path, "r", encoding="utf-8") as f:
                risk_data = json.load(f)
            rows = risk_data.get("rows", [])
            for row in rows:
                ticker = row.get("ticker", "UNKNOWN")
                for key, val in row.items():
                    if key not in ("ticker", "status", "action", "strategy", "score", "entry_price", "data_verified", "reason_codes"):
                        # Extract individual risk rule verdicts
                        if isinstance(val, dict):
                            rule_code = key
                            verdict = val.get("verdict", "not_evaluated")
                            message = val.get("message", "")
                            cursor.execute("""
                            INSERT INTO risk_verdicts (run_id, ticker, rule_code, verdict, message)
                            VALUES (?, ?, ?, ?, ?)
                            """, (run_id, ticker, rule_code, verdict, message))
        except Exception as e:
            logger.error(f"Failed to insert risk verdicts for run {run_id}: {e}")
            
    # 4. Insert account attribution
    attrib_path = run_dir / "account_attribution.json"
    if attrib_path.exists():
        try:
            with open(attrib_path, "r", encoding="utf-8") as f:
                attrib_data = json.load(f)
            summary = attrib_data.get("summary", {})
            cursor.execute("""
            INSERT INTO account_attributions (run_id, timestamp, price_effect, fx_effect, holdings_effect, cash_effect)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (
                run_id, 
                timestamp, 
                summary.get("price_effect_pct", 0.0),
                summary.get("fx_effect_pct", 0.0),
                summary.get("holdings_effect_pct", 0.0),
                summary.get("cash_effect_pct", 0.0)
            ))
        except Exception as e:
            logger.error(f"Failed to insert account attribution for run {run_id}: {e}")
            
    # 5. Insert stock lifecycles
    lifecycle_path = run_dir / "stock_lifecycle.json"
    if lifecycle_path.exists():
        try:
            with open(lifecycle_path, "r", encoding="utf-8") as f:
                lc_data = json.load(f)
            items = lc_data.get("items", [])
            for item in items:
                ticker = item.get("ticker", "UNKNOWN")
                current_state = item.get("current_state", "watch")
                duration = item.get("duration_days", 0)
                cursor.execute("""
                INSERT INTO stock_lifecycles (run_id, ticker, current_state, duration_days)
                VALUES (?, ?, ?, ?)
                """, (run_id, ticker, current_state, duration))
        except Exception as e:
            logger.error(f"Failed to insert stock lifecycles for run {run_id}: {e}")
            
    # 6. Insert failure patterns
    patterns_path = run_dir / "failure_patterns.json"
    if patterns_path.exists():
        try:
            with open(patterns_path, "r", encoding="utf-8") as f:
                pat_data = json.load(f)
            summary = pat_data.get("summary", {})
            cursor.execute("""
            INSERT INTO failure_patterns (run_id, repeated_code_count, active_streak_count, top_code)
            VALUES (?, ?, ?, ?)
            """, (
                run_id,
                summary.get("repeated_code_count", 0),
                summary.get("active_streak_count", 0),
                summary.get("top_code", "NONE")
            ))
        except Exception as e:
            logger.error(f"Failed to insert failure patterns for run {run_id}: {e}")
            
    conn.commit()
    conn.close()
    return True

def sync_all_runs(db_path: Path, paths: Any) -> int:
    init_db(db_path)
    count = 0
    if not paths.runs_dir.exists():
        return count
        
    for item in paths.runs_dir.iterdir():
        if item.is_dir():
            # Check if there is a manifest.json
            if (item / "manifest.json").exists():
                if insert_run_data(db_path, paths, item.name):
                    count += 1
    return count

def get_trends(db_path: Path, limit_days: int = 30) -> dict[str, Any]:
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # We query runs sorted by timestamp desc, limiting to the last N runs
    cursor.execute("""
    SELECT run_id, timestamp, execution_status, safety_decision, failure_code, score
    FROM runs
    ORDER BY timestamp DESC
    LIMIT ?
    """, (limit_days,))
    runs_rows = [dict(row) for row in cursor.fetchall()]
    
    if not runs_rows:
        conn.close()
        return {
            "run_count": 0,
            "success_rate": 0.0,
            "avg_health_score": 0.0,
            "failure_distribution": {},
            "signal_counts": [],
            "top_blockers": [],
            "runs": []
        }
        
    run_ids = [r["run_id"] for r in runs_rows]
    placeholders = ",".join("?" for _ in run_ids)
    
    # 1. Success rate
    success_runs = sum(1 for r in runs_rows if r["execution_status"] == "success")
    success_rate = (success_runs / len(runs_rows)) * 100.0 if runs_rows else 0.0
    
    # 2. Avg health score
    avg_health = sum(r["score"] for r in runs_rows) / len(runs_rows) if runs_rows else 0.0
    
    # 3. Failure distribution
    failure_dist = {}
    for r in runs_rows:
        code = r["failure_code"]
        if code and code != "NONE":
            failure_dist[code] = failure_dist.get(code, 0) + 1
            
    # 4. Signals count per run
    cursor.execute(f"""
    SELECT run_id, COUNT(*) as count
    FROM signals
    WHERE run_id IN ({placeholders})
    GROUP BY run_id
    """, run_ids)
    sig_counts = {row["run_id"]: row["count"] for row in cursor.fetchall()}
    
    # 5. Top blocked risk rules
    cursor.execute(f"""
    SELECT rule_code, COUNT(*) as count
    FROM risk_verdicts
    WHERE run_id IN ({placeholders}) AND verdict = 'blocked'
    GROUP BY rule_code
    ORDER BY count DESC
    LIMIT 5
    """, run_ids)
    top_blockers = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    # Combine signals counts into runs
    for r in runs_rows:
        r["signal_count"] = sig_counts.get(r["run_id"], 0)
        
    return {
        "run_count": len(runs_rows),
        "success_rate": round(success_rate, 1),
        "avg_health_score": round(avg_health, 1),
        "failure_distribution": failure_dist,
        "top_blockers": top_blockers,
        "runs": runs_rows
    }
