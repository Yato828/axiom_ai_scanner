/* Original DegenMixer artwork. Native Canvas 2D; no third-party runtime or scene. */
export const STILL_TIME = 8.5;

export function ribbonPoint(u, strand, time, width, height, branch = 0, pointer = { x: 0, y: 0 }) {
  const phase = time * 0.24 + pointer.x * 0.18;
  const swell = Math.sin(u * 6.1 - phase);
  const ripple = Math.sin(u * 12.8 + phase * 0.7);
  const fold = Math.cos(u * 6.5 - phase * 0.65 + branch * 1.9);
  const spread = height * (branch ? 0.041 : 0.082);
  return {
    x: u * width,
    y: height * (0.29 + swell * 0.105 + ripple * 0.018 + branch * 0.045)
      + strand * spread * fold
      + strand * strand * height * 0.026 * Math.sin(u * 8.3 + phase)
      + branch * height * 0.026 * Math.sin(u * 11 - phase)
      + pointer.y * height * 0.014,
  };
}

export function createSignalWave(canvas) {
  const context = canvas.getContext('2d', { alpha: true });
  if (!context) throw new Error('Canvas 2D is unavailable.');
  const container = canvas.parentElement;
  const hero = container.closest('.hero');
  const pointer = { x: 0, y: 0 };
  const target = { x: 0, y: 0 };
  let width = 0;
  let height = 0;
  let frame = 0;
  let time = STILL_TIME;
  let raf = 0;
  let lastTime = 0;
  let paused = false;
  let destroyed = false;
  const initialBounds = container.getBoundingClientRect();
  let inView = initialBounds.bottom > 0 && initialBounds.top < innerHeight;

  function path(strand, branch = 0) {
    const steps = width < 600 ? 100 : 150;
    context.beginPath();
    for (let step = 0; step <= steps; step++) {
      const point = ribbonPoint(step / steps, strand, time, width, height, branch, pointer);
      if (!step) context.moveTo(point.x, point.y);
      else context.lineTo(point.x, point.y);
    }
  }

  function render() {
    if (!width || !height || destroyed) return;
    context.clearRect(0, 0, width, height);
    context.globalCompositeOperation = 'source-over';
    const halo = context.createRadialGradient(width * 0.78, height * 0.42, 0, width * 0.78, height * 0.42, height * 0.56);
    halo.addColorStop(0, 'rgba(200,210,222,0.055)');
    halo.addColorStop(0.6, 'rgba(180,194,210,0.02)');
    halo.addColorStop(1, 'rgba(180,194,210,0)');
    context.fillStyle = halo;
    context.fillRect(0, 0, width, height);

    // Fixed, deterministic stars avoid sparkle noise or a different image on every load.
    const starCount = width < 600 ? 26 : 64;
    for (let index = 0; index < starCount; index++) {
      const x = ((Math.sin(index * 127.1 + 42) * 43758.5453) % 1 + 1) % 1;
      const y = ((Math.sin(index * 311.7 + 19) * 17593.179) % 1 + 1) % 1;
      const alpha = (0.09 + 0.16 * (0.5 + Math.sin(time * 0.6 + index) * 0.5)) * (y < 0.6 ? 1 : 0.3);
      context.fillStyle = `rgba(225,229,235,${alpha})`;
      context.beginPath();
      context.arc(x * width, y * height, index % 9 === 0 ? 1.1 : 0.55, 0, Math.PI * 2);
      context.fill();
    }

    context.globalCompositeOperation = 'lighter';
    const light = context.createLinearGradient(0, 0, width, 0);
    light.addColorStop(0, 'rgba(215,224,236,0)');
    light.addColorStop(0.13, 'rgba(215,224,236,0.36)');
    light.addColorStop(0.46, 'rgba(252,250,242,0.92)');
    light.addColorStop(0.75, 'rgba(236,240,246,0.72)');
    light.addColorStop(1, 'rgba(215,224,236,0)');
    context.strokeStyle = light;
    context.lineCap = 'round';

    // Soft light under fine individual strands creates the appearance of folded silk.
    context.save();
    context.globalAlpha = 0.13;
    context.lineWidth = width < 600 ? 8 : 13;
    context.shadowColor = 'rgba(225,235,255,0.65)';
    context.shadowBlur = 30;
    path(0);
    context.stroke();
    context.restore();

    const strands = width < 600 ? 62 : 100;
    for (let index = 0; index < strands; index++) {
      const v = index / (strands - 1) * 2 - 1;
      context.globalAlpha = 0.095 + Math.pow(Math.abs(v), 5) * 0.22;
      context.lineWidth = index % 11 === 0 ? 0.85 : 0.48;
      path(v);
      context.stroke();
    }
    for (let index = 0; index < Math.floor(strands * 0.55); index++) {
      const v = index / (Math.floor(strands * 0.55) - 1) * 2 - 1;
      context.globalAlpha = 0.055 + Math.abs(v) * 0.07;
      context.lineWidth = 0.45;
      path(v, 1);
      context.stroke();
    }
    context.globalAlpha = 0.6;
    context.lineWidth = 0.7;
    path(-1);
    context.stroke();
    path(1);
    context.stroke();
    context.globalAlpha = 1;
    context.globalCompositeOperation = 'source-over';
    canvas.dataset.frame = String(++frame);
  }

  function tick(timestamp) {
    raf = 0;
    if (paused || !inView || document.hidden || destroyed) return;
    if (!lastTime) lastTime = timestamp;
    const elapsed = timestamp - lastTime;
    if (elapsed >= 1000 / 30) {
      time += Math.min(elapsed / 1000, 0.1);
      pointer.x += (target.x - pointer.x) * 0.045;
      pointer.y += (target.y - pointer.y) * 0.045;
      lastTime = timestamp;
      render();
    }
    raf = requestAnimationFrame(tick);
  }

  function syncLoop() {
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
    lastTime = 0;
    if (!paused && inView && !document.hidden && !destroyed) raf = requestAnimationFrame(tick);
  }

  function resize() {
    const bounds = container.getBoundingClientRect();
    width = bounds.width;
    height = bounds.height;
    const dpi = Math.min(devicePixelRatio || 1, 1.5);
    canvas.width = Math.round(width * dpi);
    canvas.height = Math.round(height * dpi);
    context.setTransform(dpi, 0, 0, dpi, 0, 0);
    render();
  }

  function movePointer(event) {
    if (event.pointerType !== 'mouse') return;
    const bounds = hero.getBoundingClientRect();
    target.x = (event.clientX - bounds.left) / bounds.width - 0.5;
    target.y = (event.clientY - bounds.top) / bounds.height - 0.5;
  }
  function resetPointer() { target.x = 0; target.y = 0; }

  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(container);
  const visibilityObserver = new IntersectionObserver(entries => {
    inView = entries[0].isIntersecting;
    syncLoop();
  }, { rootMargin: '50px' });
  visibilityObserver.observe(container);
  hero.addEventListener('pointermove', movePointer, { passive: true });
  hero.addEventListener('pointerleave', resetPointer);
  document.addEventListener('visibilitychange', syncLoop);
  resize();
  syncLoop();

  return {
    setPaused(value) { paused = value; syncLoop(); },
    destroy() {
      destroyed = true;
      syncLoop();
      resizeObserver.disconnect();
      visibilityObserver.disconnect();
      hero.removeEventListener('pointermove', movePointer);
      hero.removeEventListener('pointerleave', resetPointer);
      document.removeEventListener('visibilitychange', syncLoop);
    },
  };
}
