const displayId = "inky-main";
let display = null;

const byId = (id) => document.getElementById(id);

function setMessage(message, kind = "") {
  const element = byId("job-message");
  element.textContent = message;
  element.className = `message ${kind}`;
}

function setStatus(message, kind = "neutral") {
  const element = byId("connection-status");
  element.textContent = message;
  element.className = `status ${kind}`;
}

function renderDisplay(nextDisplay) {
  display = nextDisplay;
  byId("orientation").value = display.orientation;
  byId("rotation").value = display.rotation;
  byId("preview-frame").className = `preview-frame ${display.orientation}`;
  byId("preview-meta").textContent = `${display.width} × ${display.height} • ${display.orientation}`;
  byId("display-details").innerHTML = [
    ["Current revision", display.current_revision],
    ["Desired revision", display.desired_revision],
    ["Last heartbeat", display.last_seen_at ? new Date(display.last_seen_at).toLocaleString() : "Not seen yet"],
    ["Last error", display.last_error || "None"],
  ].map(([label, value]) => `<div><dt>${label}</dt><dd>${value}</dd></div>`).join("");
  setStatus(display.last_seen_at ? "Agent seen" : "Waiting for agent", display.last_seen_at ? "good" : "neutral");
}

async function loadDisplay() {
  const response = await fetch(`/api/v1/displays/${displayId}`);
  if (!response.ok) throw new Error("Unable to load the display settings");
  renderDisplay(await response.json());
}

async function pollJob(jobId) {
  const response = await fetch(`/api/v1/jobs/${jobId}`);
  if (!response.ok) throw new Error("Unable to read the display job");
  const job = await response.json();
  if (job.preview_url) {
    const image = byId("preview");
    image.src = `${job.preview_url}?v=${job.artifact_sha256}`;
    image.hidden = false;
    byId("preview-placeholder").hidden = true;
  }
  const labels = {
    queued: "Queued for rendering…",
    rendering: "Rendering the seven-colour artifact…",
    ready: display?.last_seen_at
      ? "Ready for the Pi to refresh the display."
      : "Artifact is ready; waiting for the offline Pi to reconnect.",
    started: "The Pi is refreshing the e-ink panel…",
    completed: "The display refresh completed.",
    superseded: "Replaced by a newer display request.",
    failed: `Could not prepare the image: ${job.error_message || "unknown error"}`,
  };
  setMessage(labels[job.status] || `Job state: ${job.status}`, job.status === "failed" ? "error" : "");
  if (["queued", "rendering", "ready", "started"].includes(job.status)) {
    window.setTimeout(() => pollJob(jobId).catch((error) => setMessage(error.message, "error")), 1500);
  }
  await loadDisplay();
}

byId("image-file").addEventListener("change", (event) => {
  const file = event.target.files[0];
  byId("file-label").textContent = file ? file.name : "Choose a JPEG, PNG, or WebP";
});

byId("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = byId("image-file").files[0];
  if (!file) return;
  const button = byId("submit-button");
  button.disabled = true;
  setMessage("Uploading original image…");
  try {
    const formData = new FormData();
    formData.append("file", file);
    const upload = await fetch("/api/v1/assets", { method: "POST", body: formData });
    if (!upload.ok) throw new Error((await upload.json()).detail || "Upload failed");
    const asset = await upload.json();
    const renderSettings = {
      fit_mode: byId("fit-mode").value,
      dither_mode: byId("dither-mode").value,
      content_rotation: 0,
      focal_point_x: 0.5,
      focal_point_y: 0.5,
      flip_horizontal: false,
      flip_vertical: false,
    };
    const displayNow = await fetch(`/api/v1/displays/${displayId}/display-now`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ asset_id: asset.id, render_settings: renderSettings }),
    });
    if (!displayNow.ok) throw new Error((await displayNow.json()).detail || "Display request failed");
    const job = await displayNow.json();
    await pollJob(job.id);
  } catch (error) {
    setMessage(error.message, "error");
  } finally {
    button.disabled = false;
  }
});

byId("settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const response = await fetch(`/api/v1/displays/${displayId}/settings`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        orientation: byId("orientation").value,
        rotation: Number(byId("rotation").value),
      }),
    });
    if (!response.ok) throw new Error("Could not save panel settings");
    renderDisplay(await response.json());
    setMessage("Panel settings saved. New renders will use this orientation.");
  } catch (error) {
    setMessage(error.message, "error");
  }
});

loadDisplay().catch((error) => setMessage(error.message, "error"));
