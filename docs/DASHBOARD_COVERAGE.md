# Dashboard Coverage Map

Refresh this document with:

```bash
jayu inventory dashboard-coverage
```

## Coverage Rules

| Coverage | Meaning |
| --- | --- |
| api_and_ui | Backend API and dashboard section both exist |
| api_only | API exists but no visible dashboard section was detected |
| ui_only | UI section exists but no API route was detected |
| not_exposed | Feature is implemented but not dashboard-facing |

## Initial Watch List

| Area | Expected Dashboard Surface |
| --- | --- |
| Feature Inventory | Settings/System page, `GET /api/v1/features` |
| Toss Order History | Personal finance order panels, `GET /api/v1/toss/orders` |
| Toss Order Detail | Detail panel, `GET /api/v1/toss/orders/{orderId}` |
| Release Readiness | CLI first, dashboard summary later |
| Backup Manager | Settings/System page |

The generated JSON lives at `state/dashboard_coverage_map.json`.

