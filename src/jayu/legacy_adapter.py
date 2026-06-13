from __future__ import annotations

import copy
import json
import os

import numpy as np

from .optimizer import DEFAULT_PARAMS, fill_missing_params


def migrate_json_structure(data):
    if not isinstance(data, dict):
        return {}
    migrated = {}
    for ticker, val in data.items():
        if not isinstance(val, dict):
            continue
        has_regimes = any(r in val for r in ["bull", "bear", "sideways"])
        if has_regimes:
            migrated[ticker] = {}
            for r in ["bull", "bear", "sideways"]:
                r_data = val.get(r, {})
                if isinstance(r_data, dict) and "params" in r_data:
                    migrated[ticker][r] = copy.deepcopy(r_data)
                    migrated[ticker][r]["params"] = fill_missing_params(r_data["params"])
                else:
                    migrated[ticker][r] = {
                        "ticker": ticker,
                        "params": copy.deepcopy(DEFAULT_PARAMS),
                        "metrics": {},
                        "val_metrics": {},
                    }
        else:
            r_data = copy.deepcopy(val)
            if "params" in r_data:
                r_data["params"] = fill_missing_params(r_data["params"])
            else:
                r_data["params"] = copy.deepcopy(DEFAULT_PARAMS)
            migrated[ticker] = {
                "bull": copy.deepcopy(r_data),
                "bear": copy.deepcopy(r_data),
                "sideways": copy.deepcopy(r_data),
            }
    return migrated


def migrate_gene_pool(data):
    if not isinstance(data, dict):
        return {}
    migrated = {}
    for ticker, val in data.items():
        if not isinstance(val, dict):
            migrated[ticker] = {"bull": [], "bear": [], "sideways": []}
            for item in val:
                if isinstance(item, dict) and "params" in item:
                    item_copy = copy.deepcopy(item)
                    item_copy["params"] = fill_missing_params(item_copy["params"])
                    migrated[ticker]["bull"].append(item_copy)
                    migrated[ticker]["bear"].append(copy.deepcopy(item_copy))
                    migrated[ticker]["sideways"].append(copy.deepcopy(item_copy))
        else:
            has_regimes = any(r in val for r in ["bull", "bear", "sideways"])
            if has_regimes:
                migrated[ticker] = {}
                for r in ["bull", "bear", "sideways"]:
                    migrated[ticker][r] = []
                    for item in val.get(r, []):
                        if isinstance(item, dict) and "params" in item:
                            item_copy = copy.deepcopy(item)
                            item_copy["params"] = fill_missing_params(item_copy["params"])
                            migrated[ticker][r].append(item_copy)
            else:
                migrated[ticker] = {"bull": [], "bear": [], "sideways": []}
    return migrated


def migrate_history(data):
    if not isinstance(data, dict):
        return {}
    migrated = {}
    for ticker, val in data.items():
        if not isinstance(val, dict):
            migrated[ticker] = {
                "bull": copy.deepcopy(val),
                "bear": copy.deepcopy(val),
                "sideways": copy.deepcopy(val),
            }
        else:
            has_regimes = any(r in val for r in ["bull", "bear", "sideways"])
            if has_regimes:
                migrated[ticker] = val
            else:
                migrated[ticker] = {"bull": [], "bear": [], "sideways": []}
    return migrated


# ── 오늘의 진입 신호 ─────────────────────────────────────────────


def numpy_to_python(obj):
    if isinstance(obj, dict):
        return {k: numpy_to_python(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [numpy_to_python(v) for v in obj]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    return obj


def save_json(obj, path):
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(numpy_to_python(obj), f, ensure_ascii=False, indent=2)
        if os.path.exists(tmp_path):
            os.replace(tmp_path, path)
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError as cleanup_error:
                print(f"  ⚠ temporary JSON cleanup failed ({tmp_path}): {cleanup_error}")
        raise e


def load_json(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  ⚠ JSON 파싱 오류 ({path}): {e}")
            # 손상된 파일 백업 후 기본값 반환
            backup = path + ".corrupt"
            try:
                import shutil

                shutil.copy2(path, backup)
                print(f"    → 손상 파일 백업: {backup}")
            except Exception as backup_error:
                print(f"    ⚠ 손상 파일 백업 실패: {backup_error}")
    return default if default is not None else {}


# ── 메인 실행 ────────────────────────────────────────────────────
