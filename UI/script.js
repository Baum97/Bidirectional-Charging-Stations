// ===== Tabs behavior (like example) =====
let activeTab = null;
const tabs = document.querySelectorAll('.tab');
const controls = document.querySelectorAll('.controls');

function openTab(id) {
  const side = document.getElementById('side');
  const tab = tabs[id];
  const ctrl = controls[id];
  if (activeTab === id) {
    side.classList.remove('open');
    tab.classList.remove('open');
    ctrl.classList.remove('open');
    activeTab = null;
  } else {
    side.classList.add('open');
    tab.classList.add('open');
    ctrl.classList.add('open');
    if (activeTab !== null) {
      tabs[activeTab].classList.remove('open');
      controls[activeTab].classList.remove('open');
    }
    activeTab = id;
  }
}
tabs.forEach((t, i) => t.addEventListener('click', () => openTab(i)));
openTab(0);

// ===== Map + bbox selection (Leaflet) =====
const map = L.map('map').setView([52.52, 13.4], 13);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap contributors',
}).addTo(map);

let firstCorner = null;
let rectLayer = null;
const bboxEl = document.getElementById('bbox');
const scenarioEl = document.getElementById('scenario');
const canvasToggle = document.getElementById('canvas-toggle');
const selectionCanvas = document.getElementById('selectionCanvas');

let powerLayer = null;

// --- Helpers to derive voltage and colors ---

function getFeatureVoltageKv(feature) {
  const p = feature.properties || {};
  if (p.voltage_kv != null) {
    return Number(p.voltage_kv);
  }
  if (!p.voltage) return null;
  const str = String(p.voltage);
  const matches = str.replace(',', '.').match(/\d+(\.\d+)?/g);
  if (!matches) return null;
  let maxVal = 0;
  for (const m of matches) {
    const v = parseFloat(m);
    if (v > maxVal) maxVal = v;
  }
  if (maxVal > 1000) return maxVal / 1000.0;
  return maxVal;
}

function colorForVoltageKv(v) {
  if (v == null || isNaN(v)) return '#999999';  // unknown / miscellaneous
  if (v >= 380) return '#ff0000';   // extra high voltage
  if (v >= 220) return '#ff4500';   // high voltage
  if (v >= 110) return '#ff8800';   // sub-transmission
  if (v >= 36)  return '#ffdd00';   // medium
  if (v >= 1)   return '#00aa00';   // low voltage distribution
  return '#5555ff';                 // really low stuff
}

function showPowerGrid(geojson) {
  if (!geojson || !geojson.features || !geojson.features.length) {
    console.log('No power grid features in this area');
    if (powerLayer) {
      map.removeLayer(powerLayer);
      powerLayer = null;
    }
    return;
  }

  if (powerLayer) {
    map.removeLayer(powerLayer);
  }

  powerLayer = L.geoJSON(geojson, {
    style: function (feature) {
      const kv = getFeatureVoltageKv(feature);
      const color = colorForVoltageKv(kv);

      // Thicker for higher voltages
      let weight = 2;
      if (kv >= 220) weight = 4;
      else if (kv >= 110) weight = 3;

      if (feature.geometry && feature.geometry.type === 'Polygon') {
        return {
          color,
          weight: 2,
          fillColor: color,
          fillOpacity: 0.15,
          opacity: 0.9,
        };
      }
      return {
        color,
        weight,
        opacity: 0.9,
      };
    },
    pointToLayer: function (feature, latlng) {
      const kv = getFeatureVoltageKv(feature);
      const color = colorForVoltageKv(kv);
      const p = feature.properties || {};
      const kind = p.kind || '';
      const baseRadius = kind === 'power_node' ? 4 : 3;
      const radius = kv != null && kv >= 110 ? baseRadius + 2 : baseRadius;
      return L.circleMarker(latlng, {
        radius,
        color,
        fillColor: color,
        fillOpacity: 0.9,
      });
    },
    onEachFeature: function (feature, layer) {
      const p = feature.properties || {};
      const kv = getFeatureVoltageKv(feature);
      const lines = [];

      if (p.power) lines.push(`<b>${p.power}</b>`);
      if (p.name) lines.push(p.name);
      if (kv != null && !isNaN(kv)) lines.push(`Voltage: ${kv.toFixed(1)} kV`);
      else if (p.voltage) lines.push(`Voltage: ${p.voltage}`);
      if (p.circuits) lines.push(`Circuits: ${p.circuits}`);
      if (p.operator) lines.push(`Operator: ${p.operator}`);

      if (lines.length) layer.bindPopup(lines.join('<br>'));
    }
  }).addTo(map);
}

// Function to display charging stations on the map
function showChargingStations(geojson) {
  console.log("Charging stations GeoJSON data:", geojson);

  if (!geojson || !geojson.features || !geojson.features.length) {
    console.error("No charging station data available.");
    return;
  }

  console.log(`Displaying ${geojson.features.length} charging stations on the map.`);

  const bounds = L.geoJSON(geojson).getBounds();
  map.fitBounds(bounds); // Automatically zoom to the area of the charging stations

  // Custom charging station icon using SVG
  const chargingIcon = L.divIcon({
    className: 'charging-station-icon',
    html: `<svg width="32" height="32" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="6" y="2" width="12" height="20" rx="2" fill="#4CAF50" stroke="#2E7D32" stroke-width="1.5"/>
      <path d="M9 6 L12 10 L10.5 10 L13 14" stroke="#FFF" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
      <circle cx="9" cy="18" r="1" fill="#FFF"/>
      <circle cx="15" cy="18" r="1" fill="#FFF"/>
      <path d="M18 8 L20 6 M20 6 L20 12 M20 6 L22 8" stroke="#2E7D32" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>`,
    iconSize: [32, 32],
    iconAnchor: [16, 32],
    popupAnchor: [0, -32]
  });

  const chargingStationLayer = L.geoJSON(geojson, {
    pointToLayer: function (feature, latlng) {
      return L.marker(latlng, { icon: chargingIcon });
    },
    onEachFeature: function (feature, layer) {
      const props = feature.properties || {};
      const name = props.name || "Unknown Station";
      const capacity = props.capacity || "Unknown Capacity";
      layer.bindPopup(`<strong>${name}</strong><br>Capacity: ${capacity}`);
    },
  });

  chargingStationLayer.addTo(map);
}

// Function to display GeoJSON areas on the map
function showGeoJsonAreas(geojson) {
  console.log("GeoJSON data:", geojson);

  if (!geojson || !geojson.features || !geojson.features.length) {
    console.error("Invalid or empty GeoJSON data.");
    return;
  }

  console.log(`Displaying ${geojson.features.length} areas on the map.`);

  // Add the GeoJSON layer to the map
  const geoJsonLayer = L.geoJSON(geojson, {
    style: function (feature) {
      return {
        color: "#ff7800", // Border color
        weight: 2,        // Border width
        fillColor: "#ffcc00", // Fill color
        fillOpacity: 0.5  // Fill opacity
      };
    },
    onEachFeature: function (feature, layer) {
      // Bind a popup to each feature
      const props = feature.properties || {};
      const popupContent = `
        <strong>Cluster ID:</strong> ${props.cluster_id || "N/A"}<br>
        <strong>Count:</strong> ${props.count_low_soc || "N/A"}<br>
        <strong>Mean SOC:</strong> ${props.mean_soc || "N/A"}<br>
        <strong>Estimated Chargers:</strong> ${props.estimated_chargers || "N/A"}
      `;
      layer.bindPopup(popupContent);
    }
  });

  // Fit the map to the bounds of the GeoJSON layer
  const bounds = geoJsonLayer.getBounds();
  map.fitBounds(bounds);

  // Add the layer to the map
  geoJsonLayer.addTo(map);
}

function formatBbox(bounds) {
  const sw = bounds.getSouthWest();
  const ne = bounds.getNorthEast();
  const minLat = sw.lat.toFixed(6);
  const minLon = sw.lng.toFixed(6);
  const maxLat = ne.lat.toFixed(6);
  const maxLon = ne.lng.toFixed(6);
  return `${minLon},${minLat},${maxLon},${maxLat}`; // lon,lat order for SUMO osmGet
}

function getBboxArray(bounds) {
  const sw = bounds.getSouthWest();
  const ne = bounds.getNorthEast();
  return [sw.lng, sw.lat, ne.lng, ne.lat]; // [minLon, minLat, maxLon, maxLat]
}

function enableSelection(enabled) {
  if (!enabled) {
    firstCorner = null;
    if (rectLayer) { map.removeLayer(rectLayer); rectLayer = null; }
    bboxEl.textContent = 'none';
    map.off('click');
    selectionCanvas.style.display = 'none';
    return;
  }
  selectionCanvas.style.display = 'block';
  map.on('click', (ev) => {
    if (!firstCorner) {
      firstCorner = ev.latlng;
      if (rectLayer) { map.removeLayer(rectLayer); rectLayer = null; }
    } else {
      const second = ev.latlng;
      const bounds = L.latLngBounds(firstCorner, second);
      if (rectLayer) map.removeLayer(rectLayer);
      rectLayer = L.rectangle(bounds, { color: '#2b8a3e', weight: 2, fillOpacity: 0.1 }).addTo(map);
      bboxEl.textContent = formatBbox(bounds);
      firstCorner = null;
    }
  });
}

canvasToggle?.addEventListener('change', (e) => enableSelection(e.target.checked));
enableSelection(false);

function currentBboxBounds() {
  if (!rectLayer) return null;
  return rectLayer.getBounds();
}

function defaultScenarioName() {
  const s = scenarioEl.value.trim();
  if (s) return s;
  const d = new Date();
  const pad = (n) => n.toString().padStart(2, '0');
  return `scenario_${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

// ===== Build via local helper or show commands =====
const statusEl2 = document.getElementById('buildStatus');
const simStatusEl = document.getElementById('simStatus');
const sendLocalBtn = document.getElementById('sendLocal');
const copyBashBtn = document.getElementById('copyBash');
const copyPwshBtn = document.getElementById('copyPowershell');

function makeCommands(bounds, scenario) {
  const [minLon, minLat, maxLon, maxLat] = getBboxArray(bounds);
  const bash = `set -euo pipefail
SCEN='${scenario}'
BASE='data/scenarios/'
mkdir -p "$BASE$SCEN"
cd "$BASE$SCEN"
python3 "$SUMO_HOME/tools/osmGet.py" --bbox "${minLon},${minLat},${maxLon},${maxLat}" -p map -d .
OSM="$(ls -1 map*.osm.xml map*.osm.gz map*.osm.bz2 2>/dev/null | head -n1)"
if [ -z "$OSM" ]; then echo 'No OSM file produced by osmGet' >&2; ls -la; exit 1; fi
"${SUMO_HOME}/bin/netconvert" --osm-files "$OSM" -o net.net.xml --speed-in-kmh --proj.utm
python3 "$SUMO_HOME/tools/randomTrips.py" -n net.net.xml -o trips.trips.xml -r routes.rou.xml --seed 42 --end 3600 --period 1.0
cat > sim.sumocfg << 'EOF'
<configuration>
  <input net-file="net.net.xml" route-files="routes.rou.xml"/>
  <time begin="0" end="3600"/>
</configuration>
EOF

echo "Run: sumo-gui -c sim.sumocfg"`;
  const pwsh = `$ErrorActionPreference = 'Stop'
$SCEN='${scenario}'
$BASE='data/scenarios/'
$DIR = Join-Path $BASE $SCEN
New-Item -ItemType Directory -Force -Path $DIR | Out-Null
Set-Location $DIR
python "$env:SUMO_HOME\\tools\\osmGet.py" --bbox "${minLon},${minLat},${maxLon},${maxLat}" -p map -d .
$osm = Get-ChildItem -Name map*.osm.xml, map*.osm.gz, map*.osm.bz2 | Select-Object -First 1
if (-not $osm) { Get-ChildItem | Out-String | Write-Host; throw 'No OSM file produced by osmGet' }
& "$env:SUMO_HOME\\bin\\netconvert.exe" --osm-files $osm -o net.net.xml --speed-in-kmh --proj.utm
python "$env:SUMO_HOME\\tools\\randomTrips.py" -n net.net.xml -o trips.trips.xml -r routes.rou.xml --seed 42 --end 3600 --period 1.0
'$cfg = "<configuration> <input net-file=\\"net.net.xml\\" route-files=\\"routes.rou.xml\\"/> <time begin=\\"0\\" end=\\"3600\\"/> </configuration>"; $cfg | Set-Content sim.sumocfg -Encoding ASCII'
Write-Host "Run: sumo-gui -c sim.sumocfg"`;
  return { bash, pwsh };
}

// Find the last built scenarioDir (reuse statusEl2 or store it globally)
let lastScenarioDir = null;

// Patch sendToLocal to remember the scenarioDir
async function sendToLocal(bounds, scenario) {
  const body = { bbox: getBboxArray(bounds), scenario };
  statusEl2.textContent = 'Contacting local helper at http://127.0.0.1:8787 ...';
  try {
    const res = await fetch('http://127.0.0.1:8787/build', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const j = await res.json();
    statusEl2.textContent = `Success: ${j.message || 'scenario created'} at ${j.scenarioDir || ''}`;
    lastScenarioDir = j.scenarioDir; // <-- store for simulation
  } catch (err) {
    statusEl2.textContent = 'Local helper not reachable or failed. Use copy commands below.';
  }
}


async function downloadOSMData(bounds, scenario) {
  const body = { bbox: getBboxArray(bounds), scenario };
  statusEl2.textContent = 'Downloading OSM data...';
  try {
    const res = await fetch('http://127.0.0.1:8787/build', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const j = await res.json();
    statusEl2.textContent = `OSM data downloaded: ${j.message || ''}`;
    lastScenarioDir = j.scenarioDir;

    // Visualize power grid
    if (j.powerGrid) {
      showPowerGrid(j.powerGrid);
    }

    // Visualize real charging stations
    if (j.realChargingStations) {
      console.log("Calling showChargingStations with data:", j.realChargingStations);
      showChargingStations(j.realChargingStations);
    } else {
      console.error("No realChargingStations data in the response.");
    }

    // Visualize heatmap GeoJSON areas (clusters where charging is needed)
    if (j.heatmapGeoJSON) {
      console.log("Calling showGeoJsonAreas with data:", j.heatmapGeoJSON);
      showGeoJsonAreas(j.heatmapGeoJSON);
    } else {
      console.error("No heatmapGeoJSON data in the response.");
    }


  } catch (err) {
    statusEl2.textContent = 'Failed to download OSM data: ' + err;
    console.error(err);
  }
}

// Add this function to start simulation
async function startSimulation() {
  if (!lastScenarioDir) {
    simStatusEl.textContent = 'No scenario built yet. Please build a scenario first.';
    return;
  }
  simStatusEl.textContent = 'Starting simulation...';
  try {
    const res = await fetch('http://127.0.0.1:8787/start-simulation', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenarioDir: lastScenarioDir }),
    });
    const j = await res.json();
    if (j.ok) {
      simStatusEl.textContent = 'Simulation started!';
    } else {
      simStatusEl.textContent = 'Simulation failed: ' + (j.error || 'unknown error');
    }
  } catch (err) {
    simStatusEl.textContent = 'Failed to start simulation: ' + err;
  }
}

async function generateTrips() {
  if (!lastScenarioDir) {
    simStatusEl.textContent = 'No scenario built yet. Please build a scenario first.';
    return;
  }
  simStatusEl.textContent = 'Generating trips...';
  try {
    const res = await fetch('http://127.0.0.1:8787/generate-trips', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenarioDir: lastScenarioDir, num_persons: 250, ev_share: 0.6 }),
    });
    const j = await res.json();
    if (j.ok) {
      simStatusEl.textContent = 'Trips generated successfully!';
    } else {
      simStatusEl.textContent = 'Failed to generate trips: ' + (j.error || 'unknown error');
    }
  } catch (err) {
    simStatusEl.textContent = 'Failed to generate trips: ' + err;
  }
}

sendLocalBtn?.addEventListener('click', async () => {
  const b = currentBboxBounds();
  if (!b) {
    alert('Please select an area by clicking two corners on the map.');
    return;
  }
  await sendToLocal(b, defaultScenarioName());
});

const downloadOSMDataBtn = document.getElementById('downloadOSMData');

downloadOSMDataBtn?.addEventListener('click', async () => {
  const b = currentBboxBounds();
  if (!b) {
    alert('Please select an area by clicking two corners on the map.');
    return;
  }
  await downloadOSMData(b, defaultScenarioName());
});

copyBashBtn?.addEventListener('click', async () => {
  const b = currentBboxBounds();
  if (!b) { alert('Please select an area first.'); return; }
  const c = makeCommands(b, defaultScenarioName());
  await navigator.clipboard.writeText(c.bash);
  statusEl2.textContent = 'Bash commands copied to clipboard.';
});

copyPwshBtn?.addEventListener('click', async () => {
  const b = currentBboxBounds();
  if (!b) { alert('Please select an area first.'); return; }
  const c = makeCommands(b, defaultScenarioName());
  await navigator.clipboard.writeText(c.pwsh);
  statusEl2.textContent = 'PowerShell commands copied to clipboard.';
});

// ===== Existing WebSocket demo =====
const statusEl = document.getElementById('wsStatus');
const logEl = document.getElementById('log');
const msgEl = document.getElementById('msg');
const sendBtn = document.getElementById('send');
const pingBtn = document.getElementById('ping');
const clearBtn = document.getElementById('clear');

function log(msg, dir = 'in') {
  const ts = new Date().toISOString();
  logEl.textContent += `\n[${ts}] ${dir === 'out' ? '>>' : '<<'} ${msg}`;
  logEl.scrollTop = logEl.scrollHeight;
}

const wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
const WS_PATH = (window.__WS_PATH__ || '/ws');
let ws = new WebSocket(`${wsProto}://${location.host}${WS_PATH}`);

ws.addEventListener('open', () => {
  statusEl.textContent = 'WebSocket: connected';
});

ws.addEventListener('close', () => {
  statusEl.textContent = 'WebSocket: disconnected';
});

ws.addEventListener('message', (ev) => {
  log(ev.data);
});

sendBtn.addEventListener('click', () => {
  const value = msgEl.value || 'Hello from browser!';
  ws.send(JSON.stringify({ type: 'message', value }));
  log(JSON.stringify({ type: 'message', value }), 'out');
});

pingBtn.addEventListener('click', () => {
  ws.send(JSON.stringify({ type: 'ping' }));
  log(JSON.stringify({ type: 'ping' }), 'out');
});

clearBtn.addEventListener('click', () => {
  logEl.textContent = '';
});

// ===== Position search and geolocation =====
const latLonEl = document.getElementById('lat_lon');

document.getElementById('buttonLatLon').addEventListener('click', () => {
  const parts = latLonEl.value.trim().split(/\s+/);
  if (parts.length === 2) {
    const lat = parseFloat(parts[0]);
    const lon = parseFloat(parts[1]);
    if (!isNaN(lat) && !isNaN(lon)) map.setView([lat, lon], 16);
  }
});

document.getElementById('buttonSearch').addEventListener('click', async () => {
  const q = document.getElementById('address').value.trim();
  if (!q) return;
  try {
    const res = await fetch(`https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}&format=json&limit=1`);
    const data = await res.json();
    if (data && data[0]) {
      const lat = parseFloat(data[0].lat);
      const lon = parseFloat(data[0].lon);
      map.setView([lat, lon], 16);
      latLonEl.value = `${lat.toFixed(6)} ${lon.toFixed(6)}`;
    }
  } catch (e) {
    console.error(e);
  }
});

document.getElementById('buttonCurrent').addEventListener('click', () => {
  if (!navigator.geolocation) return;
  navigator.geolocation.getCurrentPosition((pos) => {
    const { latitude: lat, longitude: lon } = pos.coords;
    map.setView([lat, lon], 16);
    latLonEl.value = `${lat.toFixed(6)} ${lon.toFixed(6)}`;
  });
});

// Generate Scenario button mirrors Send to Local SUMO
document.getElementById('export-button').addEventListener('click', async () => {
  const b = currentBboxBounds();
  if (!b) {
    alert('Please select an area by clicking two corners on the map.');
    return;
  }
  await sendToLocal(b, defaultScenarioName());
});

document.getElementById('startSimulation').addEventListener('click', startSimulation);
document.getElementById('generateTrips').addEventListener('click', generateTrips);
