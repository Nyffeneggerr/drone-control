// Ties virtual joysticks / Gamepad API to the WS control protocol from server.py,
// and renders telemetry pushed back over the same socket.

const CONTROL_SEND_HZ = 20;
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 10000;

const leftStick = new VirtualJoystick(document.getElementById('stick-left'), {
  selfCenterX: true,   // yaw snaps back to center
  selfCenterY: false,  // throttle holds position
  initialY: 1,         // start at bottom = zero throttle
});
const rightStick = new VirtualJoystick(document.getElementById('stick-right'), {
  selfCenterX: true,   // roll
  selfCenterY: true,   // pitch
});

let ws = null;
let gamepadIndex = null;
let reconnectAttempts = 0;
let reconnectTimer = null;

function setStatus(state, linkText = '') {
  const bar = document.getElementById('status-bar');
  const text = document.getElementById('status-text');
  bar.className = `status status-${state}`;
  text.textContent = state.toUpperCase();
  document.getElementById('link-text').textContent = linkText;
}

function scheduleReconnect() {
  if (reconnectTimer !== null) return; // a reconnect is already pending, don't stack timers
  const delaySec = Math.min(RECONNECT_BASE_MS * 2 ** reconnectAttempts, RECONNECT_MAX_MS) / 1000;
  reconnectAttempts += 1;
  setStatus('disconnected', `retrying in ${delaySec}s (attempt ${reconnectAttempts})`);
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, delaySec * 1000);
}

function connect() {
  setStatus('connecting');
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const socket = new WebSocket(`${proto}://${location.host}/ws`);
  ws = socket;

  // Guard every handler against a stale socket: once a newer connect() has
  // replaced `ws`, this socket's late-firing events must not touch UI state
  // (a slow onclose from a superseded socket previously stomped a newer,
  // already-successful onopen's CONNECTED status).
  socket.onopen = () => {
    if (ws !== socket) return;
    reconnectAttempts = 0;
    setStatus('connected');
  };
  socket.onclose = () => {
    if (ws !== socket) return;
    setStatus('disconnected');
    scheduleReconnect();
  };
  socket.onerror = () => socket.close();
  socket.onmessage = (event) => {
    if (ws !== socket) return;
    const msg = JSON.parse(event.data);
    if (msg.type === 'telemetry') updateHud(msg);
  };
}

function updateHud(t) {
  const armed = document.getElementById('hud-armed');
  armed.textContent = t.armed ? 'ARMED' : 'disarmed';
  armed.className = `hud-value ${t.armed ? 'bad' : 'good'}`;

  document.getElementById('hud-mode').textContent = t.mode;

  const battery = document.getElementById('hud-battery');
  if (t.battery_voltage != null) {
    battery.textContent = `${t.battery_voltage.toFixed(1)}V${t.battery_remaining != null ? ` (${t.battery_remaining}%)` : ''}`;
    battery.className = `hud-value ${t.battery_status === 'critical' ? 'bad' : t.battery_status === 'low' ? 'warn' : ''}`;
  } else {
    battery.textContent = '--';
  }

  const batteryBanner = document.getElementById('battery-banner');
  batteryBanner.textContent = t.battery_status === 'critical' ? '⚠ BATTERY CRITICAL' : '⚠ BATTERY LOW';
  batteryBanner.classList.toggle('banner-warn', t.battery_status === 'low');
  batteryBanner.classList.toggle('hidden', t.battery_status !== 'low' && t.battery_status !== 'critical');

  const gps = document.getElementById('hud-gps');
  gps.textContent = `fix=${t.gps_fix_type} sats=${t.satellites_visible}`;
  gps.className = `hud-value ${t.gps_fix_type < 3 ? 'warn' : 'good'}`;

  document.getElementById('hud-alt').textContent = t.alt != null ? `${t.alt.toFixed(1)}m` : '--';

  document.getElementById('link-text').textContent = t.link_ok ? 'FC link OK' : 'FC LINK LOST';
  if (!t.link_ok) setStatus('disconnected', 'FC LINK LOST');

  document.getElementById('fence-banner').classList.toggle('hidden', !t.fence_breached);
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

document.getElementById('btn-arm').addEventListener('click', () => send({ type: 'arm' }));
document.getElementById('btn-disarm').addEventListener('click', () => send({ type: 'disarm' }));
document.getElementById('mode-select').addEventListener('change', (e) => send({ type: 'mode', mode: e.target.value }));

window.addEventListener('gamepadconnected', (e) => {
  gamepadIndex = e.gamepad.index;
  document.getElementById('gamepad-indicator').classList.remove('hidden');
  document.getElementById('sticks').style.display = 'none';
});
window.addEventListener('gamepaddisconnected', () => {
  gamepadIndex = null;
  document.getElementById('gamepad-indicator').classList.add('hidden');
  document.getElementById('sticks').style.display = 'flex';
});

function readControls() {
  if (gamepadIndex !== null) {
    const gp = navigator.getGamepads()[gamepadIndex];
    if (gp) {
      // Standard mapping: left stick axes[0]/[1] = yaw/throttle, right stick axes[2]/[3] = roll/pitch.
      // Adjust to taste per physical controller.
      const yaw = gp.axes[0] ?? 0;
      const throttleAxis = gp.axes[1] ?? 1; // -1 (up) = full throttle on most gamepads
      const roll = gp.axes[2] ?? 0;
      const pitch = gp.axes[3] ?? 0;
      return {
        x: Math.round(roll * 1000),
        y: Math.round(-pitch * 1000),
        z: Math.round(((1 - throttleAxis) / 2) * 1000),
        r: Math.round(yaw * 1000),
      };
    }
  }
  return {
    x: Math.round(rightStick.x * 1000),
    y: Math.round(-rightStick.y * 1000),
    z: Math.round(((1 - leftStick.y) / 2) * 1000),
    r: Math.round(leftStick.x * 1000),
  };
}

setInterval(() => {
  const c = readControls();
  send({ type: 'control', ...c });
}, 1000 / CONTROL_SEND_HZ);

connect();

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/service-worker.js');
}
