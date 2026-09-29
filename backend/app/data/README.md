# Data directory (not committed except this file)

| File | Written by | Owner |
| --- | --- | --- |
| `graph_drive.graphml` | `scripts/fetch_osm.py` | P2 |
| `facilities.json` | `scripts/fetch_osm.py` | P2 |
| `gtfs/{routes,trips,shapes,stops}.txt` | `scripts/build_gtfs_subset.py` | P3 |

Until these exist, the API serves a demo grid and demo transit so the UI works end to end.
Responses carry `is_demo_data: true` and the UI shows a banner.
