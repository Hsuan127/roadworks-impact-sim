# Data directory

| File | Written by | Owner | Committed |
| --- | --- | --- | --- |
| `graph_drive.graphml`, `graph_walk.graphml`, `meta.json` | `scripts/fetch_osm.py` | P2 | yes |
| `facilities.json` | `scripts/fetch_osm.py` | P2 | yes |
| `aadt_by_edge.json` | `scripts/fetch_aadt.py` | P2 | yes |
| `gtfs/{routes,trips,shapes,stops,stop_routes}.txt` | `scripts/build_gtfs_subset.py` | P3 | no |

P2's files are committed so nobody needs osmnx or a live Overpass call to run the app.
Until these exist, the API serves a demo grid and demo transit so the UI works end to end.
Responses carry `is_demo_data: true` and the UI shows a banner.

The GTFS subset is not committed, so **every machine builds its own** — including whichever laptop
runs the demo. Build it from the steps below, or ask the owner for the files.

## gtfs/ (P3)

### 1. Download

[GTFS Schedule on DataVic](https://discover.data.vic.gov.au/dataset/gtfs-schedule) — a single
`gtfs.zip`, about 290 MB, refreshed weekly. Keep it outside the repo. (The same dataset is
mirrored on the [Transport Victoria portal](https://opendata.transport.vic.gov.au/dataset/gtfs-schedule).)

### 2. Extract twice

`gtfs.zip` holds one **numbered folder per mode**, each containing another
`google_transit.zip`. The script reads extracted folders, so the inner zip has to come out
too. Only three of the eleven modes reach the demo area:

| Folder | Mode | `route_type` in the data |
| --- | --- | --- |
| `3` | Metropolitan tram | `0` |
| `4` | Metropolitan bus | `3`, `701` |
| `2` | Metropolitan train | `400` |

The rest are regional and interstate services that never come near Flemington Road.

```bash
cd <where you unzipped gtfs.zip>
for d in 2 3 4; do unzip -q -o "$d/google_transit.zip" -d "$d/google_transit"; done
```

### 3. Build the subset

```bash
cd backend && source .venv/bin/activate
python scripts/build_gtfs_subset.py <gtfs>/{3,4,2}/google_transit
```

Give it a couple of minutes: the bus and train `shapes.txt` are about 90 MB each.

### 4. Check it worked

```bash
python -c "
from app.impact.transit import load_transit
import collections
r, s = load_transit()
print(collections.Counter(x.mode for x in r), len(r), 'routes,', len(s), 'stops')
"
```

The 2026-09-29 feed gives `Counter({'bus': 46, 'tram': 17, 'train': 15}) 78 routes, 427 stops`,
and the four files come to ~47 MB, nearly all of it `shapes.txt`.

### Things that cost time to find out

- **Python 3.14 cannot create the venv** — `ensurepip` fails partway and leaves a broken
  `.venv/`. Delete it and use 3.13 or 3.11.
- `route_type` uses GTFS **extended** codes, not only the basic 0–7 set: metro trains are
  `400` and some buses `701`. `ROUTE_TYPE_MODE` in `app/impact/transit.py` maps both.
- The feed sets no `parent_station`, so each direction of a stop is a separate row ~30 m
  away under the same name. `transit_impact()` keeps the nearest of each name.
- `shapes.txt` keeps whole route shapes, so ~92 % of its points sit far outside the 2 km
  box — route 59's full run out to Airport West, for instance. Correct, just large.
  Clipping would mean splitting the three quarters of shapes that leave the box and
  come back, otherwise the gap gets joined by a straight line that can falsely cross
  the closed segment.
