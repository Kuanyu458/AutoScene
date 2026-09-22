(function () {
  "use strict";

  const pathParts = window.location.pathname.split("/").filter(Boolean);
  const projectId = decodeURIComponent(pathParts[1] || "");
  const root = document.querySelector(".editor-shell");
  const segmentsEl = document.getElementById("segments");
  const statusEl = document.getElementById("status-label");
  const revisionEl = document.getElementById("revision-label");
  const durationEl = document.getElementById("duration-label");
  const emptyEl = document.getElementById("empty-state");
  const saveButton = document.getElementById("save-button");
  const backLink = document.getElementById("back-link");
  let timeline = null;
  let operations = [];

  root.dataset.projectId = projectId;
  backLink.href = "/p/" + encodeURIComponent(projectId);

  function setStatus(message, error) {
    statusEl.textContent = message;
    statusEl.style.color = error ? "#fb7185" : "#5eead4";
  }

  function number(value, fallback) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function render() {
    if (!timeline || !Array.isArray(timeline.segments)) return;
    segmentsEl.replaceChildren();
    emptyEl.hidden = timeline.segments.length !== 0;
    const duration = timeline.segments.reduce((sum, segment) => sum + Math.max(0, number(segment.source_out_seconds, 0) - number(segment.source_in_seconds, 0)) / Math.max(number(segment.speed, 1), .1), 0);
    durationEl.textContent = duration.toFixed(2) + "s";
    revisionEl.textContent = "revision " + timeline.revision + (operations.length ? " · unsaved" : "");

    timeline.segments.forEach((segment, index) => {
      const card = document.createElement("article");
      card.className = "segment";
      card.dataset.segmentId = segment.id;

      const head = document.createElement("div");
      head.className = "segment-head";
      const id = document.createElement("div");
      id.className = "segment-id";
      id.textContent = (index + 1) + ". " + segment.id;
      const source = document.createElement("div");
      source.className = "segment-source";
      source.textContent = segment.source;
      head.append(id, source);

      const fields = document.createElement("div");
      fields.className = "segment-fields";
      [
        ["source in", "source_in_seconds"],
        ["source out", "source_out_seconds"],
      ].forEach(([label, key]) => {
        const wrapper = document.createElement("label");
        wrapper.className = "field";
        wrapper.textContent = label;
        const input = document.createElement("input");
        input.type = "number";
        input.step = "0.001";
        input.min = "0";
        input.value = number(segment[key], 0).toFixed(3);
        input.addEventListener("change", () => {
          const nextIn = key === "source_in_seconds" ? number(input.value, segment.source_in_seconds) : segment.source_in_seconds;
          const nextOut = key === "source_out_seconds" ? number(input.value, segment.source_out_seconds) : segment.source_out_seconds;
          if (nextOut <= nextIn) {
            setStatus("source out must be greater than source in", true);
            input.value = number(segment[key], 0).toFixed(3);
            return;
          }
          operations.push({ op: "trim", segment_id: segment.id, source_in_seconds: nextIn, source_out_seconds: nextOut });
          segment.source_in_seconds = nextIn;
          segment.source_out_seconds = nextOut;
          render();
          setStatus("Trim queued; save to create revision");
        });
        wrapper.appendChild(input);
        fields.appendChild(wrapper);
      });

      const actions = document.createElement("div");
      actions.className = "segment-actions";
      [["↑", -1], ["↓", 1]].forEach(([label, direction]) => {
        const button = document.createElement("button");
        button.className = "icon-button";
        button.type = "button";
        button.textContent = label;
        button.title = direction < 0 ? "Move up" : "Move down";
        button.disabled = (direction < 0 && index === 0) || (direction > 0 && index === timeline.segments.length - 1);
        button.addEventListener("click", () => {
          const ids = timeline.segments.map((item) => item.id);
          const swap = index + direction;
          [ids[index], ids[swap]] = [ids[swap], ids[index]];
          operations.push({ op: "reorder", segment_ids: ids });
          const current = timeline.segments[index];
          timeline.segments[index] = timeline.segments[swap];
          timeline.segments[swap] = current;
          render();
          setStatus("Reorder queued; save to create revision");
        });
        actions.appendChild(button);
      });

      const zoom = document.createElement("div");
      zoom.className = "zoom-row";
      const zoomLabel = document.createElement("label");
      zoomLabel.textContent = "Zoom keyframe";
      const timeInput = document.createElement("input");
      timeInput.type = "number"; timeInput.min = "0"; timeInput.step = "0.001"; timeInput.placeholder = "time (s)";
      const scaleInput = document.createElement("input");
      scaleInput.type = "number"; scaleInput.min = "1"; scaleInput.step = ".01"; scaleInput.value = "1.2"; scaleInput.placeholder = "scale";
      const zoomButton = document.createElement("button");
      zoomButton.className = "icon-button"; zoomButton.type = "button"; zoomButton.textContent = "Add";
      zoomButton.addEventListener("click", () => {
        const time = number(timeInput.value, NaN);
        if (!Number.isFinite(time)) { setStatus("Enter a keyframe time", true); return; }
        operations.push({ op: "set_zoom_keyframe", segment_id: segment.id, time_seconds: time, scale: number(scaleInput.value, 1.2), x: .5, y: .5, easing: "ease-in-out" });
        setStatus("Zoom keyframe queued; save to create revision");
        timeInput.value = "";
      });
      zoom.append(zoomLabel, timeInput, scaleInput, zoomButton);
      (timeline.zoom_keyframes || []).filter((item) => item.segment_id === segment.id).forEach((item) => {
        const chip = document.createElement("span"); chip.className = "zoom-chip"; chip.textContent = item.time_seconds + "s ×" + item.scale; zoom.appendChild(chip);
      });

      card.append(head, fields, actions, zoom);
      segmentsEl.appendChild(card);
    });
  }

  async function load() {
    try {
      const response = await fetch("/api/project/" + encodeURIComponent(projectId) + "/edit-timeline");
      if (!response.ok) throw new Error((await response.json()).detail || response.statusText);
      timeline = await response.json();
      operations = [];
      render();
      setStatus("Timeline loaded");
    } catch (error) {
      setStatus("Could not load timeline: " + error.message, true);
      emptyEl.hidden = false;
    }
  }

  saveButton.addEventListener("click", async () => {
    if (!timeline || !operations.length) { setStatus("No unsaved overrides"); return; }
    saveButton.disabled = true;
    try {
      const response = await fetch("/api/project/" + encodeURIComponent(projectId) + "/edit-timeline", {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ base_revision: timeline.revision, operations }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || response.statusText);
      timeline = body; operations = []; render(); setStatus("Saved revision " + timeline.revision);
    } catch (error) {
      setStatus("Save failed: " + error.message, true);
    } finally { saveButton.disabled = false; }
  });

  load();
}());
