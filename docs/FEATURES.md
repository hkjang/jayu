# Jayu Feature Inventory

This file is the initial inventory seed. Refresh it with:

```bash
jayu inventory build
```

## Managed Statuses

Feature status is managed in `configs/feature_status.yaml`.

| Status | Meaning |
| --- | --- |
| stable | Release-critical core surface |
| beta | Usable, still evolving |
| experimental | Early or agent-facing feature |
| deprecated | Kept for compatibility only |

## Core Matrix Seed

| Feature | Status | Primary Files | Surface |
| --- | --- | --- | --- |
| CLI | stable | `src/jayu/cli.py` | `jayu ...` commands |
| Dashboard | stable | `src/jayu/dashboard.py`, `src/jayu/dashboard_static/*` | Web console |
| Settings | stable | `src/jayu/settings.py` | Config validation |
| Engine | stable | `src/jayu/engine.py` | Research and backtest |
| Risk | stable | `src/jayu/risk.py` | Safety gates |
| Toss | beta | `src/jayu/toss.py`, `src/jayu/toss_orders.py` | Read-only broker data |
| Personal Finance | beta | `investment_goal_planner.py`, `cashflow_planner.py`, `personal_investment_score.py` | Goal and coaching pages |
| Backup Manager | beta | `src/jayu/backup_manager.py` | System operations |
| Agent Mode | experimental | `src/jayu/agent_mode.py`, `src/jayu/jayu_mcp_server.py` | Agent/MCP surface |
| Legacy Bridges | deprecated | `src/jayu/legacy_adapter.py`, `src/jayu/legacy_cli.py` | Compatibility |

## Generated Outputs

`jayu inventory build` writes:

| Output | Purpose |
| --- | --- |
| `state/feature_inventory.json` | Machine-readable feature inventory |
| `docs/FEATURES.md` | Human-readable feature matrix |

