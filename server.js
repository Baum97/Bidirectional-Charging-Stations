import express from 'express';
import http from 'http';
import { WebSocketServer } from 'ws';

const PORT = process.env.PORT || 8080;
const WS_PATH = process.env.WS_PATH || '/ws';

const app = express();

// Basic health endpoint
app.get('/health', (_, res) => {
  res.json({ status: 'ok' });
});

// Serve static files from public/
app.use(express.static('public', {
  extensions: ['html'],
}));

// Also expose example assets for styling/images
app.use('/webWizard_example', express.static('webWizard_example'));

// Create HTTP server and attach WebSocket server to it
const server = http.createServer(app);
const wss = new WebSocketServer({ noServer: true });

// Track connections for broadcast and heartbeats
function heartbeat() {
  this.isAlive = true;
}

wss.on('connection', (ws, request) => {
  ws.isAlive = true;
  ws.on('pong', heartbeat);

  ws.send(JSON.stringify({ type: 'hello', message: 'Connected to WebSocket server', path: request.url }));

  ws.on('message', (data) => {
    let payload = data.toString();
    try {
      const parsed = JSON.parse(payload);
      payload = parsed;
    } catch (_) {}

    // Simple echo + broadcast example
    ws.send(JSON.stringify({ type: 'echo', data: payload }));
  });

  ws.on('close', () => {
    // Connection closed
  });
});

// Periodic ping to detect broken connections
const interval = setInterval(() => {
  wss.clients.forEach((ws) => {
    if (ws.isAlive === false) return ws.terminate();
    ws.isAlive = false;
    ws.ping();
  });
}, 30000);

server.on('close', () => clearInterval(interval));

server.on('upgrade', (request, socket, head) => {
  const { url } = request;
  if (!url || !url.startsWith(WS_PATH)) {
    socket.destroy();
    return;
  }
  wss.handleUpgrade(request, socket, head, (ws) => {
    wss.emit('connection', ws, request);
  });
});

server.listen(PORT, () => {
  console.log(`Server listening on http://localhost:${PORT}`);
  console.log(`WebSocket available at ws://localhost:${PORT}${WS_PATH}`);
});
