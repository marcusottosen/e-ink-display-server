const displayId = "inky-main";
let display = null;
let showTrash = false;

const byId = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value).replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#039;", '"': "&quot;" })[character]);

async function api(url, options = {}) {
  const response = await fetch(url, options);
  if (response.ok || response.status === 204) return response.status === 204 ? null : response.json();
  const payload = await response.json().catch(() => ({}));
  const detail = typeof payload.detail === "string" ? payload.detail : payload.detail?.message;
  throw new Error(detail || "Request failed");
}

function setMessage(id, message, kind = "") {
  const element = byId(id);
  element.textContent = message;
  element.className = `message ${kind}`;
}

function showView(view) {
  document.querySelectorAll(".view").forEach((element) => {
    element.hidden = element.id !== `${view}-view`;
    element.classList.toggle("active", !element.hidden);
  });
  document.querySelectorAll(".tab").forEach((element) => element.classList.toggle("active", element.dataset.view === view));
  if (view === "gallery") loadGallery();
  if (view === "albums") loadAlbums();
  if (view === "activity") loadActivity();
  if (view === "settings") loadConnectionSettings();
}

function renderDisplay(nextDisplay) {
  display = nextDisplay;
  byId("orientation").value = display.orientation;
  byId("rotation").value = display.rotation;
  byId("preview-frame").className = `preview-frame ${display.orientation}`;
  byId("preview-meta").textContent = `${display.width} × ${display.height} • ${display.orientation}`;
  const details = [["Current revision", display.current_revision], ["Desired revision", display.desired_revision], ["Last heartbeat", display.last_seen_at ? new Date(display.last_seen_at).toLocaleString() : "Not seen yet"], ["Last error", display.last_error || "None"]];
  byId("display-details").innerHTML = details.map(([label, value]) => `<div><dt>${label}</dt><dd>${escapeHtml(value)}</dd></div>`).join("");
  const status = byId("connection-status");
  status.textContent = display.last_seen_at ? "Agent seen" : "Waiting for agent";
  status.className = `status ${display.last_seen_at ? "good" : "neutral"}`;
}

async function loadDisplay() { renderDisplay(await api(`/api/v1/displays/${displayId}`)); }

function showPreview(url, hash) {
  const image = byId("preview");
  image.src = `${url}?v=${hash || Date.now()}`;
  image.hidden = false;
  byId("preview-placeholder").hidden = true;
}

async function pollJob(jobId) {
  const job = await api(`/api/v1/jobs/${jobId}`);
  if (job.preview_url) showPreview(job.preview_url, job.artifact_sha256);
  const labels = {
    queued: "Queued for rendering…",
    rendering: "Resizing the display image…",
    ready: display?.last_seen_at ? "Ready for the Pi to refresh the display." : "Artifact is ready; waiting for the offline Pi to reconnect.",
    started: "The Pi is refreshing the e-ink panel…",
    completed: "The display refresh completed.",
    superseded: "Replaced by a newer display request.",
    failed: `Could not prepare the image: ${job.error_message || "unknown error"}`,
  };
  setMessage("job-message", labels[job.status] || `Job state: ${job.status}`, job.status === "failed" ? "error" : "");
  await loadDisplay();
  if (["queued", "rendering", "ready", "started"].includes(job.status)) {
    window.setTimeout(() => pollJob(jobId).catch((error) => setMessage("job-message", error.message, "error")), 1500);
  }
  return job;
}

async function displayAsset(assetId) {
  const job = await api(`/api/v1/displays/${displayId}/display-now`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ asset_id: assetId }),
  });
  showView("dashboard");
  await pollJob(job.id);
}

async function loadGallery() {
  const assets = await api(`/api/v1/assets?include_deleted=${showTrash}`);
  byId("show-trash").textContent = showTrash ? "Hide trash" : "Show trash";
  byId("gallery-grid").innerHTML = assets.map((asset) => {
    const preview = asset.preview_url ? `<img src="${asset.preview_url}?v=${asset.sha256}" alt="${escapeHtml(asset.original_filename)}">` : '<div class="thumbnail-placeholder">Not rendered yet</div>';
    const action = asset.deleted_at ? `<button data-restore="${asset.id}" class="secondary">Restore</button>` : `<button data-display="${asset.id}">Display now</button><button data-delete="${asset.id}" class="danger">Trash</button>`;
    return `<article class="asset-card ${asset.deleted_at ? "trashed" : ""}"><label class="select-asset"><input type="checkbox" value="${asset.id}" ${asset.deleted_at ? "disabled" : ""}> Select</label>${preview}<h3>${escapeHtml(asset.original_filename)}</h3><p>${asset.width ? `${asset.width} × ${asset.height}` : "Waiting to render"} • ${(asset.file_size / 1024 / 1024).toFixed(1)} MiB</p><div class="asset-actions">${action}</div></article>`;
  }).join("") || "<p class=\"empty\">No images here yet. Upload one from the dashboard.</p>";
  byId("gallery-grid").querySelectorAll("[data-display]").forEach((button) => button.addEventListener("click", () => displayAsset(button.dataset.display).catch((error) => setMessage("gallery-message", error.message, "error"))));
  byId("gallery-grid").querySelectorAll("[data-delete]").forEach((button) => button.addEventListener("click", () => deleteAssets([button.dataset.delete])));
  byId("gallery-grid").querySelectorAll("[data-restore]").forEach((button) => button.addEventListener("click", async () => { await api(`/api/v1/assets/${button.dataset.restore}/restore`, { method: "POST" }); setMessage("gallery-message", "Image restored."); loadGallery(); }));
}

async function deleteAssets(assetIds) {
  if (!assetIds.length || !window.confirm(`Move ${assetIds.length} image(s) to Trash?`)) return;
  const result = await api("/api/v1/assets/bulk-delete", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ asset_ids: assetIds }),
  });
  setMessage("gallery-message", result.deleted_ids.length ? `Moved ${result.deleted_ids.length} image(s) to Trash.` : "Nothing moved.");
  loadGallery();
}

function fillAssetSelect(select, assets, selected = []) {
  const visible = assets.filter((asset) => !asset.deleted_at);
  const ordered = [...selected.map((id) => visible.find((asset) => asset.id === id)).filter(Boolean), ...visible.filter((asset) => !selected.includes(asset.id))];
  select.innerHTML = ordered.map((asset) => `<option value="${asset.id}" ${selected.includes(asset.id) ? "selected" : ""}>${escapeHtml(asset.original_filename)}</option>`).join("");
}

const inputDate = (value) => value ? new Date(value).toISOString().slice(0, 16) : "";
const isoDate = (value) => value ? new Date(value).toISOString() : null;

function moveSelectedOptions(select, direction) {
  const selected = [...select.selectedOptions];
  const ordered = direction < 0 ? selected : selected.reverse();
  ordered.forEach((option) => {
    const sibling = direction < 0 ? option.previousElementSibling : option.nextElementSibling;
    if (sibling) select.insertBefore(direction < 0 ? option : sibling, direction < 0 ? sibling : option);
  });
}

async function loadAlbums() {
  const [albums, assets] = await Promise.all([api("/api/v1/albums"), api("/api/v1/assets")]);
  fillAssetSelect(byId("album-assets"), assets);
  byId("album-list").innerHTML = albums.map((album) => `<article class="album-card"><div><p class="eyebrow">${album.is_running ? "RUNNING" : "ALBUM"}</p><h3>${escapeHtml(album.name)}</h3><p>${album.items.length} images • ${album.order_mode} • every ${Math.round(album.interval_seconds / 60)} minute(s)</p><div class="album-thumbs">${album.items.map((item) => item.asset.preview_url ? `<img src="${item.asset.preview_url}?v=${item.asset.sha256}" alt="">` : "<span>○</span>").join("")}</div></div><div class="album-actions"><button data-run="${album.id}">${album.is_running ? "Restart" : "Run"}</button><button data-stop="${album.id}" class="secondary" ${album.is_running ? "" : "disabled"}>Stop</button><button data-edit="${album.id}" class="secondary">Edit</button><button data-delete-album="${album.id}" class="danger">Delete</button></div></article>`).join("") || "<p class=\"empty\">Create an album from your gallery images.</p>";
  byId("album-list").querySelectorAll("[data-run]").forEach((button) => button.addEventListener("click", async () => { await api(`/api/v1/albums/${button.dataset.run}/run`, { method: "POST" }); setMessage("album-message", "Album started; the first image is being prepared."); loadAlbums(); }));
  byId("album-list").querySelectorAll("[data-stop]").forEach((button) => button.addEventListener("click", async () => { await api(`/api/v1/albums/${button.dataset.stop}/stop`, { method: "POST" }); setMessage("album-message", "Album stopped."); loadAlbums(); }));
  byId("album-list").querySelectorAll("[data-edit]").forEach((button) => button.addEventListener("click", () => openAlbumEditor(albums.find((album) => album.id === button.dataset.edit), assets)));
  byId("album-list").querySelectorAll("[data-delete-album]").forEach((button) => button.addEventListener("click", async () => { if (!window.confirm("Delete this stopped album?")) return; await api(`/api/v1/albums/${button.dataset.deleteAlbum}`, { method: "DELETE" }); loadAlbums(); }));
}

function openAlbumEditor(album, assets) {
  if (!album) return;
  byId("album-editor").hidden = false;
  byId("editing-album-id").value = album.id;
  byId("editing-album-name").textContent = album.name;
  byId("editing-album-order").value = album.order_mode;
  byId("editing-album-interval").value = Math.round(album.interval_seconds / 60);
  byId("editing-album-fit").value = album.default_render_settings.fit_mode;
  byId("editing-album-time-zone").value = album.time_zone;
  byId("editing-album-enabled").checked = album.enabled;
  byId("editing-album-start").value = inputDate(album.schedule_start_at);
  byId("editing-album-end").value = inputDate(album.schedule_end_at);
  fillAssetSelect(byId("editing-album-assets"), assets, album.items.map((item) => item.asset_id));
  byId("album-editor").scrollIntoView({ behavior: "smooth" });
}

async function loadActivity() {
  const events = await api("/api/v1/activity");
  byId("activity-list").innerHTML = events.map((event) => `<article><div><strong>${escapeHtml(event.message)}</strong><p>${escapeHtml(event.event_type)}</p></div><time datetime="${event.created_at}">${new Date(event.created_at).toLocaleString()}</time></article>`).join("") || "<p class=\"empty\">No activity yet.</p>";
}

function renderConnectionSettings(connection) {
  byId("advertised-host").value = connection.advertised_host;
  byId("advertised-port").value = connection.advertised_port;
  byId("agent-poll-interval").value = connection.agent_poll_interval_seconds;
  byId("agent-heartbeat-interval").value = connection.agent_heartbeat_interval_seconds;
  byId("agent-auth-required").checked = connection.agent_auth_required;
  byId("server-url").textContent = connection.server_url;
}

async function loadConnectionSettings() {
  try {
    renderConnectionSettings(await api("/api/v1/settings/connection"));
  } catch (error) {
    setMessage("connection-message", error.message, "error");
  }
}

document.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => showView(button.dataset.view)));
byId("image-file").addEventListener("change", (event) => { const file = event.target.files[0]; byId("file-label").textContent = file ? file.name : "Choose a JPEG, PNG, or WebP"; });
byId("upload-form").addEventListener("submit", async (event) => { event.preventDefault(); const file = byId("image-file").files[0]; if (!file) return; const button = byId("submit-button"); button.disabled = true; setMessage("job-message", "Uploading original image…"); try { const formData = new FormData(); formData.append("file", file); const asset = await api("/api/v1/assets", { method: "POST", body: formData }); const job = await api(`/api/v1/displays/${displayId}/display-now`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ asset_id: asset.id, render_settings: { fit_mode: byId("fit-mode").value, content_rotation: 0, focal_point_x: 0.5, focal_point_y: 0.5, flip_horizontal: false, flip_vertical: false } }) }); await pollJob(job.id); } catch (error) { setMessage("job-message", error.message, "error"); } finally { button.disabled = false; } });
byId("settings-form").addEventListener("submit", async (event) => { event.preventDefault(); try { renderDisplay(await api(`/api/v1/displays/${displayId}/settings`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ orientation: byId("orientation").value, rotation: Number(byId("rotation").value) }) })); setMessage("job-message", "Panel settings saved. New renders will use this orientation."); } catch (error) { setMessage("job-message", error.message, "error"); } });
byId("connection-settings-form").addEventListener("submit", async (event) => { event.preventDefault(); try { const connection = await api("/api/v1/settings/connection", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ advertised_host: byId("advertised-host").value, advertised_port: Number(byId("advertised-port").value), agent_poll_interval_seconds: Number(byId("agent-poll-interval").value), agent_heartbeat_interval_seconds: Number(byId("agent-heartbeat-interval").value), agent_auth_required: byId("agent-auth-required").checked }) }); renderConnectionSettings(connection); setMessage("connection-message", "Connection settings saved."); } catch (error) { setMessage("connection-message", error.message, "error"); } });
byId("show-trash").addEventListener("click", () => { showTrash = !showTrash; loadGallery(); });
byId("delete-selected").addEventListener("click", () => deleteAssets([...document.querySelectorAll("#gallery-grid input[type=checkbox]:checked")].map((input) => input.value)).catch((error) => setMessage("gallery-message", error.message, "error")));
byId("album-form").addEventListener("submit", async (event) => { event.preventDefault(); try { await api("/api/v1/albums", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: byId("album-name").value, asset_ids: [...byId("album-assets").selectedOptions].map((option) => option.value), order_mode: byId("album-order").value, interval_seconds: Number(byId("album-interval").value) * 60, enabled: byId("album-enabled").checked, time_zone: byId("album-time-zone").value, schedule_start_at: isoDate(byId("album-start").value), schedule_end_at: isoDate(byId("album-end").value), default_render_settings: { fit_mode: byId("album-fit").value } }) }); event.target.reset(); byId("album-time-zone").value = "Europe/Copenhagen"; byId("album-enabled").checked = true; setMessage("album-message", "Album created."); loadAlbums(); } catch (error) { setMessage("album-message", error.message, "error"); } });
byId("album-edit-form").addEventListener("submit", async (event) => { event.preventDefault(); try { const id = byId("editing-album-id").value; await api(`/api/v1/albums/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ order_mode: byId("editing-album-order").value, interval_seconds: Number(byId("editing-album-interval").value) * 60, enabled: byId("editing-album-enabled").checked, time_zone: byId("editing-album-time-zone").value, schedule_start_at: isoDate(byId("editing-album-start").value), schedule_end_at: isoDate(byId("editing-album-end").value), default_render_settings: { fit_mode: byId("editing-album-fit").value } }) }); await api(`/api/v1/albums/${id}/items`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ asset_ids: [...byId("editing-album-assets").selectedOptions].map((option) => option.value) }) }); setMessage("album-message", "Album updated."); loadAlbums(); } catch (error) { setMessage("album-message", error.message, "error"); } });
byId("item-up").addEventListener("click", () => moveSelectedOptions(byId("editing-album-assets"), -1));
byId("item-down").addEventListener("click", () => moveSelectedOptions(byId("editing-album-assets"), 1));
byId("refresh-activity").addEventListener("click", () => loadActivity());
loadDisplay().catch((error) => setMessage("job-message", error.message, "error"));
