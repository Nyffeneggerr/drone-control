// Minimal virtual joystick: touch/pointer drag inside a canvas, reports
// normalized x/y in [-1, 1]. Each axis can independently self-center on
// release (sticks) or hold its last value (throttle).
class VirtualJoystick {
  constructor(canvas, { selfCenterX = true, selfCenterY = true, initialX = 0, initialY = 0 } = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.selfCenterX = selfCenterX;
    this.selfCenterY = selfCenterY;
    this.x = initialX;
    this.y = initialY;
    this.active = false;
    this.pointerId = null;

    canvas.addEventListener('pointerdown', this._onDown.bind(this));
    canvas.addEventListener('pointermove', this._onMove.bind(this));
    canvas.addEventListener('pointerup', this._onUp.bind(this));
    canvas.addEventListener('pointercancel', this._onUp.bind(this));

    this._draw();
  }

  _onDown(e) {
    this.active = true;
    this.pointerId = e.pointerId;
    this.canvas.setPointerCapture(e.pointerId);
    this._update(e);
  }

  _onMove(e) {
    if (!this.active || e.pointerId !== this.pointerId) return;
    this._update(e);
  }

  _onUp(e) {
    if (e.pointerId !== this.pointerId) return;
    this.active = false;
    this.pointerId = null;
    if (this.selfCenterX) this.x = 0;
    if (this.selfCenterY) this.y = 0;
    this._draw();
  }

  _update(e) {
    const rect = this.canvas.getBoundingClientRect();
    const cx = rect.width / 2;
    const cy = rect.height / 2;
    const dx = (e.clientX - rect.left - cx) / cx;
    const dy = (e.clientY - rect.top - cy) / cy;
    const mag = Math.min(1, Math.hypot(dx, dy));
    const angle = Math.atan2(dy, dx);
    this.x = clamp(Math.cos(angle) * mag, -1, 1);
    this.y = clamp(Math.sin(angle) * mag, -1, 1);
    this._draw();
  }

  _draw() {
    const { ctx, canvas } = this;
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    ctx.strokeStyle = 'rgba(255,255,255,0.25)';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(w / 2, h / 2, w / 2 - 4, 0, Math.PI * 2);
    ctx.stroke();

    const knobX = w / 2 + this.x * (w / 2 - 24);
    const knobY = h / 2 + this.y * (h / 2 - 24);
    ctx.fillStyle = this.active ? '#5ce087' : 'rgba(255,255,255,0.6)';
    ctx.beginPath();
    ctx.arc(knobX, knobY, 20, 0, Math.PI * 2);
    ctx.fill();
  }
}

function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}
