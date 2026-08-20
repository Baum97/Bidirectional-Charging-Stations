# DEPRECATED!

# Biflex Static Website + WebSocket (Dockerized)

This repo provides a minimal static website with a Node.js WebSocket backend, packaged for Docker. It sets a foundation for later integrating SUMO tooling (e.g., osmWebWizard) behind the WebSocket.

## Quick Start

1. Build the image:
   - `docker build -t biflex-static-ws:local .`
2. Run the container:
   - `docker run --rm -p 8080:8080 biflex-static-ws:local`
3. Open the site:
   - Visit `http://localhost:8080`

Or use Compose:

- `docker compose up --build`

## Select OSM Area and Build Locally (SUMO_HOME)

You can select a bounding box on the site and either:

- Send it to a tiny local helper that builds a scenario using your local SUMO install (`SUMO_HOME`).
- Or copy ready‑to‑run commands (Bash or PowerShell) and run them manually.

Steps:

1) Start the web container:

- `docker compose up --build`

2) Optional: run local helper on your machine (outside Docker):

- Ensure `SUMO_HOME` is set and SUMO is installed locally.
- `python3 local/local_runner.py`
- The site will POST to `http://127.0.0.1:8787/build`.

3) In your browser open `http://localhost:8080`:

- Click two points on the map to select an area.
- Click “Send to Local SUMO (helper)” to build into `data/scenarios/<name>` using your local SUMO.
- If the helper isn’t running, use “Copy Bash/PowerShell Commands” and paste into your terminal.

Outputs are written to `data/scenarios/<scenario>/`:

- `map.osm.xml`, `net.net.xml`, `routes.rou.xml`, `sim.sumocfg`.
- Run `sumo-gui -c sim.sumocfg` to inspect in SUMO‑GUI.

## Project Layout

- `server.js`: Express static server + WebSocket endpoint on `/ws`.
- `public/index.html`: Simple client UI that connects via WebSocket and sends messages.
- `Dockerfile`: Builds a production image running on port 8080.
- `docker-compose.yml`: Convenience for local run.

## Configuration

Environment variables (with defaults):

- `PORT=8080` — HTTP and WS port inside the container.
- `WS_PATH=/ws` — WebSocket upgrade path.

## Future: Integrating SUMO / osmWebWizard

The WebSocket channel is a good bridge to orchestrate SUMO workflows from the browser. Suggested path:

1. Add a separate service/container that has SUMO installed (or use an official SUMO image) and expose a simple API/WebSocket to trigger osmWebWizard or SUMO simulations.
2. Proxy or relay messages from the frontend → Node WS → SUMO service, returning progress and results.
3. Persist artifacts (e.g., generated networks, routes) in a shared volume mounted by both containers.

You can extend `docker-compose.yml` with a `sumo` service and wire it to the Node container via an internal network. The Node layer can then expose higher-level browser commands over the WebSocket.

## Development

Run locally without Docker (requires Node 18+):

```bash
npm ci
npm run dev
# open http://localhost:8080
```

---

This is intentionally minimal to stay flexible while you add SUMO features.

## Multi-Seed Placement Study

The placement strategies are evaluated over five scenario seeds. All drivers live in
`local/` and expect `SUMO_HOME` to be set and a built reference scenario in
`data/scenarios/` (override with `BIFLEX_SRC_SCENARIO`).

Run with a fixed interpreter hash seed — without it the coupled simulation is not
reproducible, because the iteration order over the set of active vehicles decides
which of them gets power first:

```
PYTHONHASHSEED=0 python local/run_multiseed_placement.py   # reference case + Clustering, 5 seeds
PYTHONHASHSEED=0 python local/run_saturate_prune.py        # Saturate-and-Prune, 3 prune iterations
PYTHONHASHSEED=0 python local/run_extend_prune.py          # 3 further iterations, for the curve
python local/plot_placement_curve.py                       # writes journal/en/images/placement_curve.pdf
```

Results accumulate in `data/scenarios/multiseed_results.json` and
`data/scenarios/saturate_prune_results.json`; both drivers skip seeds that are
already present, so an interrupted study can be resumed by re-running them.
`local/analyze_cluster_visits.py` derives the per-cluster visit and energy figures
of the demand table from a finished run.
