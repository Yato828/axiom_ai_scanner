/* Presentation only. The feed, mixer, wallet and launch keep their existing handlers. */
(() => {
  const container = document.querySelector('#mindWave');
  const toggle = document.querySelector('#motionToggle');
  if (!container || !toggle) return;

  const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
  const storageKey = 'memorphia:background-paused';
  let scene = null;
  let loading = null;
  let failed = false;
  let userPaused = false;
  try { userPaused = localStorage.getItem(storageKey) === 'true'; } catch { /* Motion control also works without storage. */ }
  let paused = preference.matches || userPaused;

  function updateControl() {
    container.dataset.motion = paused ? 'paused' : 'running';
    toggle.setAttribute('aria-pressed', String(paused));
    toggle.setAttribute('aria-label', paused ? 'Play background animation' : 'Pause background animation');
    toggle.replaceChildren(document.createTextNode(paused ? 'Play motion ' : 'Pause motion '));
    const icon = document.createElement('span');
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = paused ? '▷' : 'Ⅱ';
    toggle.append(icon);
    if (scene) scene.setPaused(paused);
  }

  async function loadScene() {
    if (scene || failed) return;
    if (loading) return loading;
    container.dataset.sceneState = 'loading';
    loading = import('/signal-wave.js?v=1').then(({ createSignalWave }) => {
      const canvas = document.createElement('canvas');
      canvas.setAttribute('aria-hidden', 'true');
      container.append(canvas);
      scene = createSignalWave(canvas);
      container.dataset.sceneState = 'ready';
      updateControl();
    }).catch(() => {
      failed = true;
      scene?.destroy();
      container.querySelector('canvas')?.remove();
      container.dataset.sceneState = 'fallback';
      toggle.disabled = true;
      // The original vector artwork remains visible if Canvas is unavailable.
    });
    return loading;
  }

  toggle.addEventListener('click', () => {
    paused = !paused;
    userPaused = paused;
    try { localStorage.setItem(storageKey, String(paused)); } catch { /* Optional preference. */ }
    updateControl();
    if (!paused) loadScene();
  });

  preference.addEventListener('change', () => {
    paused = preference.matches || userPaused;
    updateControl();
    if (!paused) loadScene();
  });

  updateControl();
  if (paused) container.dataset.sceneState = 'poster';
  else loadScene();
})();
