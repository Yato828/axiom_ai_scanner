const tokenGrid = document.querySelector("#tokenGrid");
const emptyState = document.querySelector("#emptyState");
const scanButton = document.querySelector("#scanButton");
const narrativeButton = document.querySelector("#narrativeButton");
const limitInput = document.querySelector("#limitInput");
const refreshInput = document.querySelector("#refreshInput");
const ogInput = document.querySelector("#ogInput");
const ogPreview = document.querySelector("#ogPreview");
const statusText = document.querySelector("#statusText");
const foundCount = document.querySelector("#foundCount");
const hotCount = document.querySelector("#hotCount");
const updatedAt = document.querySelector("#updatedAt");
const narrativeGrid = document.querySelector("#narrativeGrid");
const narrativeCount = document.querySelector("#narrativeCount");
const mcapLabel = document.querySelector("#mcapLabel");

let refreshTimer = null;
let currentTokens = [];
let currentOgTokens = [];
let currentNarratives = [];

function money(value) {
  const number = Number(value || 0);
  if (number >= 1_000_000_000) return `$${(number / 1_000_000_000).toFixed(2)}B`;
  if (number >= 1_000_000) return `$${(number / 1_000_000).toFixed(2)}M`;
  if (number >= 1_000) return `$${(number / 1_000).toFixed(1)}K`;
  return `$${number.toFixed(0)}`;
}

function percent(value) {
  const number = Number(value || 0);
  return `${number >= 0 ? "+" : ""}${number.toFixed(1)}%`;
}

function ageLabel(minutes) {
  if (minutes === null || minutes === undefined) return "unknown";
  const number = Number(minutes);
  if (number < 60) return `${number.toFixed(0)}m`;
  if (number < 1440) return `${(number / 60).toFixed(1)}h`;
  return `${(number / 1440).toFixed(1)}d`;
}

function signalClass(signal) {
  return String(signal || "weak").toLowerCase();
}

function signalTitle(signal) {
  const titles = {
    HOT: "HOT - strongest mix",
    WATCH: "WATCH - solid setups",
    POTENTIAL: "POTENTIAL - manual review",
    SPECULATIVE: "SPECULATIVE - loose finds",
  };
  return titles[signal] || signal;
}

function changeClass(value) {
  return Number(value || 0) >= 0 ? "positive" : "negative";
}

function shortAddress(address) {
  if (!address || address.length <= 14) return address || "";
  return `${address.slice(0, 6)}...${address.slice(-6)}`;
}

function tokenIdentityKeys(token) {
  const address = String(token.address || token.token_address || "").trim().toLowerCase();
  const symbol = String(token.token || token.symbol || "").trim().toLowerCase();
  const name = String(token.name || "").trim().toLowerCase();
  const keys = [];
  if (address) keys.push(`address:${address}`);
  if (symbol || name) keys.push(`label:${symbol}:${name}`);
  return keys;
}

function uniqueTokens(tokens) {
  const seen = new Set();
  return (tokens || []).filter((token) => {
    const keys = tokenIdentityKeys(token);
    if (keys.length === 0 || keys.some((key) => seen.has(key))) return false;
    keys.forEach((key) => seen.add(key));
    return true;
  });
}

function fallbackImageUrl(token) {
  const label = String(token.token || token.symbol || token.name || "?")
    .slice(0, 6)
    .toUpperCase();
  const hue = [...label].reduce((sum, char) => sum + char.charCodeAt(0), 0) % 360;
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
      <rect width="120" height="120" rx="16" fill="hsl(${hue} 72% 18%)"/>
      <circle cx="92" cy="24" r="24" fill="hsl(${(hue + 82) % 360} 80% 48%)" opacity=".75"/>
      <circle cx="24" cy="96" r="30" fill="hsl(${(hue + 170) % 360} 76% 54%)" opacity=".5"/>
      <text x="60" y="69" text-anchor="middle" font-family="Arial, sans-serif" font-size="24" font-weight="800" fill="#f6f8f7">${escapeHtml(label)}</text>
    </svg>
  `;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

function imageMarkup(token, className = "token-image") {
  const fallback = fallbackImageUrl(token);
  if (token.image_url) {
    return `<img class="${className}" src="${escapeHtml(token.image_url)}" alt="${escapeHtml(token.token || token.symbol || token.name)}" loading="lazy" referrerpolicy="no-referrer" onerror="this.onerror=null;this.src='${escapeHtml(fallback)}';" />`;
  }
  return `<img class="${className}" src="${escapeHtml(fallback)}" alt="${escapeHtml(token.token || token.symbol || token.name)}" loading="lazy" />`;
}

function risksMarkup(risks) {
  if (!risks || risks.length === 0) return "";
  return risks.map((risk) => `<span class="risk">${escapeHtml(risk)}</span>`).join("");
}

function tokenCard(token) {
  const signal = signalClass(token.signal);
  const marketCap = Number(token.market_cap || token.fdv || 0);
  return `
    <article class="token-card">
      <div class="card-main">
        ${imageMarkup(token)}
        <div class="token-title">
          <h2>${escapeHtml(token.token)}</h2>
          <p>${escapeHtml(token.name || token.address)}</p>
          <p>${escapeHtml(token.chain)} &middot; ${escapeHtml(shortAddress(token.address))}</p>
        </div>
        <div class="score">
          <span class="badge ${signal}">${escapeHtml(token.signal)}</span>
          <strong>${Number(token.score || 0).toFixed(1)}</strong>
        </div>
      </div>

      <div class="metrics">
        <div class="metric">
          <span>Market cap</span>
          <strong>${money(marketCap)}</strong>
        </div>
        <div class="metric">
          <span>Liquidity</span>
          <strong>${money(token.liquidity_usd)}</strong>
        </div>
        <div class="metric">
          <span>Volume 1h</span>
          <strong>${money(token.volume_1h)}</strong>
        </div>
        <div class="metric">
          <span>Change 1h</span>
          <strong class="${changeClass(token.price_change_1h)}">${percent(token.price_change_1h)}</strong>
        </div>
        <div class="metric">
          <span>Txns 1h</span>
          <strong>${Number(token.txns_1h || 0).toLocaleString()}</strong>
        </div>
        <div class="metric">
          <span>Age</span>
          <strong>${ageLabel(token.age_minutes)}</strong>
        </div>
      </div>

      <p class="reason">${escapeHtml(token.why)}</p>
      <div class="risk-list">${risksMarkup(token.risk_flags)}</div>

      <div class="card-actions">
        <a href="${escapeHtml(token.url)}" target="_blank" rel="noreferrer">DexScreener</a>
        <button class="copy-button" type="button" data-address="${escapeHtml(token.address)}">Copy address</button>
      </div>
    </article>
  `;
}

function renderGroupedTokens(tokens) {
  const visibleTokens = uniqueTokens(tokens).filter((token) => String(token.chain || "").toLowerCase() === "solana");
  const signals = ["HOT", "WATCH", "POTENTIAL", "SPECULATIVE"];
  return signals
    .map((signal) => {
      const group = visibleTokens.filter((token) => token.signal === signal);
      if (group.length === 0) return "";
      return `
        <section class="signal-section">
          <div class="section-heading">
            <h2>${escapeHtml(signalTitle(signal))}</h2>
            <span>${group.length}</span>
          </div>
          <div class="token-grid">
            ${group.map(tokenCard).join("")}
          </div>
        </section>
      `;
    })
    .join("");
}

function narrativeCard(item, index) {
  const trendToken = currentTokens.find((token) => token.token === item.trend_token) || {};
  const ogToken = currentOgTokens.find(
    (token) => token.symbol === item.og_token && token.name === item.og_name,
  ) || { name: item.og_name, symbol: item.og_token, image_url: item.og_image_url };
  const hybridUrl = hybridStudioUrl(item, trendToken, ogToken);
  return `
    <article class="narrative-card" data-index="${index}">
      <div class="reference-strip">
        ${imageMarkup(trendToken, "reference-image")}
        <span class="mix-plus">+</span>
        ${imageMarkup(ogToken, "reference-image")}
      </div>
      <div class="narrative-body">
        <div class="narrative-topline">
          <h3>${escapeHtml(item.name)}</h3>
          <span>$${escapeHtml(item.ticker)}</span>
        </div>
        <p class="hook">${escapeHtml(item.hook)}</p>
        <p>${escapeHtml(item.visual_brief || item.narrative)}</p>
        <div class="narrative-stats">
          <span>Base: ${escapeHtml(item.trend_token)}</span>
          <span>Remix: ${escapeHtml(item.og_token)}</span>
          <span>1h: ${percent(item.change_1h)}</span>
        </div>
        <div class="narrative-actions">
          <a class="hybrid-studio-button" href="${escapeHtml(hybridUrl)}">
            Mixer studio
          </a>
          <details>
            <summary>Generation brief</summary>
            <p class="prompt-text">${escapeHtml(item.image_prompt)}</p>
          </details>
        </div>
      </div>
    </article>
  `;
}

function hybridStudioUrl(item, trendToken, ogToken) {
  const params = new URLSearchParams();
  const trendImageUrl = trendToken.image_url || item.trend_image_url || "";
  const ogImageUrl = ogToken.image_url || item.og_image_url || "";
  const trendLabel = [trendToken.token || item.trend_token, trendToken.name]
    .filter(Boolean)
    .join(" - ");
  const ogLabel = [ogToken.symbol || item.og_token, ogToken.name || item.og_name]
    .filter(Boolean)
    .join(" - ");

  params.set("image_a_url", trendImageUrl);
  params.set("image_b_url", ogImageUrl);
  params.set("image_a_label", trendLabel || "Trend token");
  params.set("image_b_label", ogLabel || "OG token");
  params.set("prompt", item.image_prompt || item.visual_brief || item.narrative || "");
  params.set("title", item.name || "");
  params.set("ticker", item.ticker ? `$${item.ticker}` : "");
  return `#studio?${params.toString()}`;
}

function renderNarratives(narratives) {
  currentNarratives = narratives;
  narrativeGrid.innerHTML = narratives.map(narrativeCard).join("");
  narrativeCount.textContent = String(narratives.length);
}

function renderOgPreview(tokens) {
  ogPreview.innerHTML = tokens
    .map(
      (token, index) => `
        <div class="og-chip" data-index="${index}">
          ${imageMarkup(token, "og-chip-image")}
          <span>${escapeHtml(token.symbol || token.name)}</span>
        </div>
      `,
    )
    .join("");
}

function formatOgList(tokens) {
  return (tokens || [])
    .map((token) =>
      [token.name || token.symbol, token.symbol || "", token.archetype || ""].join(","),
    )
    .join("\n");
}

function parseOgList(value) {
  return String(value || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [name, symbol, archetype] = line.split(/[,|;]/).map((part) => part.trim());
      return {
        name,
        symbol: symbol || name,
        archetype: archetype || "classic meme energy",
      };
    });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function loadScan() {
  const limit = Math.max(Number(limitInput.value || 0), 0);
  scanButton.disabled = true;
  statusText.textContent = "Mixing trends...";

  try {
    const query = limit > 0 ? `?limit=${encodeURIComponent(limit)}` : "";
    const response = await fetch(`/api/scan${query}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const payload = await response.json();
    const tokens = uniqueTokens(payload.tokens || []).filter(
      (token) => String(token.chain || "").toLowerCase() === "solana",
    );
    currentTokens = tokens;
    currentOgTokens = payload.og_memecoins || [];
    tokenGrid.innerHTML = renderGroupedTokens(tokens);
    renderOgPreview(currentOgTokens);
    renderNarratives(payload.narratives || []);
    resolveOgImages(currentOgTokens);
    if (!ogInput.value.trim()) ogInput.value = formatOgList(currentOgTokens);
    emptyState.hidden = tokens.length !== 0;
    foundCount.textContent = String(tokens.length);
    hotCount.textContent = String(tokens.filter((token) => token.signal === "HOT").length);
    updatedAt.textContent = payload.updated_at || "-";
    mcapLabel.textContent = `Pairs above ${money(payload.min_market_cap_usd)} mcap`;
    statusText.textContent = "Mix updated";
  } catch (error) {
    statusText.textContent = "Mix error";
    tokenGrid.innerHTML = "";
    renderNarratives([]);
    emptyState.hidden = false;
    emptyState.querySelector("h2").textContent = "Could not load market data";
    emptyState.querySelector("p").textContent = String(error.message || error);
  } finally {
    scanButton.disabled = false;
  }
}

async function resolveOgImages(tokens) {
  const queue = uniqueTokens(tokens).filter((token) => !token.image_url).slice(0, 24);
  const batchSize = 6;
  for (let index = 0; index < queue.length; index += batchSize) {
    const batch = queue.slice(index, index + batchSize);
    const changed = await Promise.all(
      batch.map(async (token) => {
        try {
          const url = `/api/og-image?name=${encodeURIComponent(token.name || "")}&symbol=${encodeURIComponent(token.symbol || "")}`;
          const response = await fetch(url, { cache: "no-store" });
          if (!response.ok) return false;
          const payload = await response.json();
          if (!payload.image_url) return false;
          token.image_url = payload.image_url;
          currentNarratives = currentNarratives.map((item) =>
            item.og_name === token.name && item.og_token === token.symbol
              ? { ...item, og_image_url: token.image_url }
              : item,
          );
          return true;
        } catch (error) {
          return false;
        }
      }),
    );
    if (changed.some(Boolean)) {
      renderOgPreview(currentOgTokens);
      renderNarratives(currentNarratives);
    }
  }
}

async function generateNarrativesFromInput() {
  narrativeButton.disabled = true;
  statusText.textContent = "Mixing narratives...";

  try {
    const response = await fetch("/api/narratives", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tokens: currentTokens,
        og_memecoins: parseOgList(ogInput.value),
        limit: 30,
      }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    renderNarratives(payload.narratives || []);
    statusText.textContent = "Narratives ready";
  } catch (error) {
    statusText.textContent = "Generation error";
  } finally {
    narrativeButton.disabled = false;
  }
}

function scheduleRefresh() {
  if (refreshTimer) window.clearInterval(refreshTimer);
  const seconds = Number(refreshInput.value || 0);
  if (seconds > 0) {
    refreshTimer = window.setInterval(loadScan, seconds * 1000);
  }
}

tokenGrid.addEventListener("click", async (event) => {
  const button = event.target.closest(".copy-button");
  if (!button) return;
  await navigator.clipboard.writeText(button.dataset.address || "");
  const oldText = button.textContent;
  button.textContent = "Copied";
  window.setTimeout(() => {
    button.textContent = oldText;
  }, 900);
});

narrativeGrid.addEventListener("click", (event) => {
  const link = event.target.closest(".hybrid-studio-button");
  if (!link) return;
  event.preventDefault();
  history.pushState(null, "", link.getAttribute("href"));
  loadInitialHybridState();
  document.querySelector("#studio")?.scrollIntoView({ behavior: "smooth", block: "start" });
  setHybridStatus("References loaded");
});

scanButton.addEventListener("click", loadScan);
narrativeButton.addEventListener("click", generateNarrativesFromInput);
refreshInput.addEventListener("change", scheduleRefresh);

const hybridForm = document.querySelector("#hybridForm");
const hybridStatusText = document.querySelector("#hybridStatus");
const hybridButton = document.querySelector("#hybridButton");
const hybridResultSlot = document.querySelector("#hybridResultSlot");
const hybridResultLink = document.querySelector("#hybridResultLink");
const imageAUrl = document.querySelector("#imageAUrl");
const imageBUrl = document.querySelector("#imageBUrl");
const imageAFile = document.querySelector("#imageAFile");
const imageBFile = document.querySelector("#imageBFile");
const imageAPreview = document.querySelector("#imageAPreview");
const imageBPreview = document.querySelector("#imageBPreview");
const imageALabel = document.querySelector("#imageALabel");
const imageBLabel = document.querySelector("#imageBLabel");
const promptInput = document.querySelector("#hybridPrompt");

const previewUrls = new Map();
const uploadableImageTypes = new Set([
  "image/bmp",
  "image/gif",
  "image/jpeg",
  "image/png",
  "image/tiff",
  "image/webp",
]);
const defaultPrompt =
  "Create a coherent DegenMixer sticker-style character or emblem from these two reference images. Preserve recognizable traits, colors, and shapes from both inputs. Keep the composition clean, high contrast, polished, and centered.";

function setHybridStatus(text) {
  hybridStatusText.textContent = text;
}

function setHybridResultMessage(text) {
  hybridResultSlot.innerHTML = "";
  const message = document.createElement("span");
  message.textContent = text;
  hybridResultSlot.append(message);
  hybridResultLink.hidden = true;
}

function setHybridResultImage(url) {
  hybridResultSlot.innerHTML = "";
  const image = document.createElement("img");
  image.src = url;
  image.alt = "Generated DegenMixer token image";
  hybridResultSlot.append(image);
  hybridResultLink.href = url;
  hybridResultLink.hidden = false;
}

function setHybridPendingMessage() {
  hybridResultSlot.innerHTML = "";
  const message = document.createElement("span");
  message.className = "pending-message";
  message.textContent = "Generation in progress. Please wait a little longer...";
  hybridResultSlot.append(message);
  hybridResultLink.hidden = true;
}

function setPreviewFromUrl(img, input, url, label, labelText) {
  input.value = url || "";
  label.textContent = labelText || label.textContent;
  if (!url) {
    img.hidden = true;
    img.removeAttribute("src");
    img.closest(".hybrid-upload")?.classList.remove("has-image");
    return;
  }

  img.src = url;
  img.hidden = false;
  img.closest(".hybrid-upload")?.classList.add("has-image");
}

function setPreviewFromFile(fileInput, img) {
  const file = fileInput.files?.[0];
  const previousUrl = previewUrls.get(fileInput.id);
  if (previousUrl) URL.revokeObjectURL(previousUrl);

  if (!file) {
    previewUrls.delete(fileInput.id);
    updateHybridButton();
    return;
  }

  const url = URL.createObjectURL(file);
  previewUrls.set(fileInput.id, url);
  img.src = url;
  img.hidden = false;
  img.closest(".hybrid-upload")?.classList.add("has-image");
  updateHybridButton();
}

function hasHybridImage(fileInput, urlInput) {
  return Boolean(fileInput.files?.[0] || urlInput.value.trim());
}

function updateHybridButton() {
  hybridButton.disabled = !(hasHybridImage(imageAFile, imageAUrl) && hasHybridImage(imageBFile, imageBUrl));
}

async function submitHybrid(event) {
  event.preventDefault();
  updateHybridButton();
  if (hybridButton.disabled) return;

  hybridButton.disabled = true;
  setHybridStatus("Generating...");
  setHybridPendingMessage();
}

async function buildHybridFormData() {
  const formData = new FormData(hybridForm);
  await setImageField(formData, "image_a", imageAFile, imageAUrl);
  await setImageField(formData, "image_b", imageBFile, imageBUrl);
  return formData;
}

async function setImageField(formData, fieldName, fileInput, urlInput) {
  const file = fileInput.files?.[0];
  if (file) {
    formData.set(fieldName, file, file.name || `${fieldName}.png`);
    return;
  }

  const url = urlInput.value.trim();
  if (!url) return;

  const blob = await uploadableBlobFromUrl(url);
  if (blob) {
    formData.set(fieldName, blob, `${fieldName}.png`);
  }
}

async function uploadableBlobFromUrl(url) {
  try {
    const response = await fetch(url);
    if (!response.ok) return null;
    const blob = await response.blob();
    if (uploadableImageTypes.has(blob.type)) return blob;
    if (blob.type === "image/svg+xml" || url.toLowerCase().includes(".svg")) {
      return await svgBlobToPng(blob);
    }
  } catch (error) {
    return null;
  }
  return null;
}

async function svgBlobToPng(svgBlob) {
  const objectUrl = URL.createObjectURL(svgBlob);
  try {
    const image = await loadImage(objectUrl);
    const size = Math.max(image.naturalWidth || 512, image.naturalHeight || 512, 512);
    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;
    const context = canvas.getContext("2d");
    context.clearRect(0, 0, size, size);
    context.drawImage(image, 0, 0, size, size);
    return await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("Could not load image preview."));
    image.src = src;
  });
}

async function readResponsePayload(response) {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch (error) {
    return { error: text };
  }
}

function loadInitialHybridState() {
  const params = hashStudioParams();
  const prompt = params.get("prompt") || defaultPrompt;
  const title = params.get("title") || "";
  const ticker = params.get("ticker") || "";

  setPreviewFromUrl(
    imageAPreview,
    imageAUrl,
    params.get("image_a_url") || "",
    imageALabel,
    params.get("image_a_label") || "Image A",
  );
  setPreviewFromUrl(
    imageBPreview,
    imageBUrl,
    params.get("image_b_url") || "",
    imageBLabel,
    params.get("image_b_label") || "Image B",
  );

  promptInput.value = buildProviderFriendlyPrompt(prompt, title, ticker);
  updateHybridButton();
}

function hashStudioParams() {
  const hash = window.location.hash || "";
  const queryStart = hash.indexOf("?");
  if (!hash.startsWith("#studio") || queryStart === -1) return new URLSearchParams();
  return new URLSearchParams(hash.slice(queryStart + 1));
}

function buildProviderFriendlyPrompt(prompt, title, ticker) {
  const base = String(prompt || defaultPrompt)
    .replace(/\bdegen\b/gi, "community")
    .replace(/\braids?\b/gi, "campaign")
    .replace(/\$[A-Za-z0-9_]+/g, "")
    .trim();
  const narrative = [title, ticker].filter(Boolean).join(" ").trim();
  return [
    "Create one polished DegenMixer sticker-style character or emblem from the two reference images.",
    "Preserve recognizable colors, shapes, and visual identity from both references.",
    "Use a clean centered composition, natural lighting, crisp edges, no UI, no tiny text.",
    narrative,
    base,
  ]
    .filter(Boolean)
    .join("\n");
}

imageAFile.addEventListener("change", () => setPreviewFromFile(imageAFile, imageAPreview));
imageBFile.addEventListener("change", () => setPreviewFromFile(imageBFile, imageBPreview));
hybridForm.addEventListener("submit", submitHybrid);
window.addEventListener("hashchange", loadInitialHybridState);

scheduleRefresh();
loadInitialHybridState();
loadScan();
