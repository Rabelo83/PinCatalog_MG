/* Detection review screen: zoom/pan viewer, box editing, drawing, actions. */
(function () {
  "use strict";

  var SRC = window.REVIEW.source;
  var FLAG_TEXT = window.REVIEW.flagDescriptions;
  var detections = window.REVIEW.detections;
  var selectedId = null;
  var multi = new Set();          // extra ids selected with Shift for merging
  var mode = "select";            // "select" | "draw"
  var view = { scale: 1, tx: 0, ty: 0 };
  var HANDLE = 10;                // handle size in screen pixels

  var $ = function (id) { return document.getElementById(id); };
  var viewport = $("viewport"), stage = $("stage"), photo = $("photo"), svg = $("overlay");
  var SVGNS = "http://www.w3.org/2000/svg";

  // ------------------------------------------------------------ geometry
  function stageSize() { return { w: photo.naturalWidth || photo.width, h: photo.naturalHeight || photo.height }; }
  function unitsPerStagePx() { return SRC.width / stageSize().w; }  // original px per displayed px

  /** Screen (client) coordinates -> original image coordinates. */
  function toImage(clientX, clientY) {
    var r = viewport.getBoundingClientRect();
    var sx = (clientX - r.left - view.tx) / view.scale;
    var sy = (clientY - r.top - view.ty) / view.scale;
    var k = unitsPerStagePx();
    return { x: sx * k, y: sy * k };
  }
  function screenToImageLength(px) { return px / view.scale * unitsPerStagePx(); }

  function applyView() {
    stage.style.transform = "translate(" + view.tx + "px," + view.ty + "px) scale(" + view.scale + ")";
    draw();
  }

  function fit() {
    var s = stageSize(), r = viewport.getBoundingClientRect();
    if (!s.w || !s.h) return;
    view.scale = Math.min(r.width / s.w, r.height / s.h) * 0.98;
    view.tx = (r.width - s.w * view.scale) / 2;
    view.ty = (r.height - s.h * view.scale) / 2;
    applyView();
  }

  function zoomAt(factor, clientX, clientY) {
    var r = viewport.getBoundingClientRect();
    var cx = clientX == null ? r.width / 2 : clientX - r.left;
    var cy = clientY == null ? r.height / 2 : clientY - r.top;
    var newScale = Math.min(20, Math.max(0.05, view.scale * factor));
    factor = newScale / view.scale;
    view.tx = cx - (cx - view.tx) * factor;
    view.ty = cy - (cy - view.ty) * factor;
    view.scale = newScale;
    applyView();
  }

  function centerOn(det) {
    var r = viewport.getBoundingClientRect();
    var k = unitsPerStagePx();
    var cx = (det.x + det.width / 2) / k * view.scale;
    var cy = (det.y + det.height / 2) / k * view.scale;
    var margin = 60;
    var sx = det.x / k * view.scale + view.tx, sy = det.y / k * view.scale + view.ty;
    var ex = (det.x + det.width) / k * view.scale + view.tx, ey = (det.y + det.height) / k * view.scale + view.ty;
    if (sx < margin || sy < margin || ex > r.width - margin || ey > r.height - margin) {
      view.tx = r.width / 2 - cx;
      view.ty = r.height / 2 - cy;
      applyView();
    }
  }

  // ------------------------------------------------------------- drawing
  function byId(id) { return detections.find(function (d) { return d.id === id; }); }

  function el(name, attrs) {
    var node = document.createElementNS(SVGNS, name);
    Object.keys(attrs).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    return node;
  }

  function draw() {
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var stroke = screenToImageLength(2);
    var handle = screenToImageLength(HANDLE);
    var font = screenToImageLength(12);
    detections.forEach(function (d, index) {
      var classes = ["det", d.status];
      if (d.id === selectedId) classes.push("selected");
      if (multi.has(d.id)) classes.push("multi");
      if (d.flags && d.flags.length) classes.push("flagged");
      var g = el("g", { "class": classes.join(" "), "data-id": d.id });
      g.appendChild(el("rect", { x: d.x, y: d.y, width: d.width, height: d.height, "stroke-width": stroke * (d.id === selectedId ? 1.8 : 1) }));
      var label = el("text", { x: d.x + stroke * 2, y: d.y - stroke * 2, "font-size": font });
      label.textContent = (index + 1) + (d.pin_code ? " " + d.pin_code : "") + (d.flags && d.flags.length ? " ⚠" : "");
      g.appendChild(label);
      if (d.id === selectedId && mode === "select") {
        [["nw", d.x, d.y], ["ne", d.x + d.width, d.y], ["sw", d.x, d.y + d.height], ["se", d.x + d.width, d.y + d.height]].forEach(function (h) {
          g.appendChild(el("rect", { "class": "handle", "data-handle": h[0], x: h[1] - handle / 2, y: h[2] - handle / 2, width: handle, height: handle }));
        });
      }
      svg.appendChild(g);
    });
    if (drawing) {
      svg.appendChild(el("rect", { "class": "drawing", x: drawing.box.x, y: drawing.box.y, width: drawing.box.width, height: drawing.box.height, "stroke-width": stroke }));
    }
  }

  // --------------------------------------------------------------- panel
  function updateCounter() {
    var pending = detections.filter(function (d) { return d.status === "pending"; }).length;
    var index = detections.findIndex(function (d) { return d.id === selectedId; });
    $("counter").textContent = (index >= 0 ? (index + 1) + " / " : "") + detections.length + " boxes · " + pending + " pending";
  }

  function showPanel() {
    updateCounter();
    var d = byId(selectedId);
    $("detail").hidden = !d;
    $("empty-panel").hidden = !!d;
    $("merge").disabled = multi.size < 1 || !d;
    $("merge").textContent = multi.size ? "Merge " + (multi.size + 1) + " boxes" : "Merge selected";
    if (!d) return;
    var status = $("det-status");
    status.textContent = d.status;
    status.className = "badge status-" + d.status;
    var pinLink = $("det-pin");
    pinLink.hidden = !d.pin_code;
    if (d.pin_code) { pinLink.textContent = d.pin_code; pinLink.href = "/pins/" + d.pin_code; }
    $("det-origin").textContent = { auto: "auto-detected", manual: "drawn by hand", merge: "merged", split: "split" }[d.origin] || d.origin;
    $("det-confidence").textContent = d.origin === "auto" ? "Detector confidence: " + Math.round(d.confidence * 100) + "%" : "";
    $("preview").src = "/api/detections/" + d.id + "/preview.jpg?v=" + encodeURIComponent(d.updated_at + d.x + d.y + d.width + d.height);
    var flags = $("flags");
    flags.innerHTML = "";
    (d.flags || []).forEach(function (f) {
      var li = document.createElement("li");
      li.textContent = FLAG_TEXT[f] || f;
      flags.appendChild(li);
    });
    $("box-x").value = d.x; $("box-y").value = d.y; $("box-w").value = d.width; $("box-h").value = d.height;
    var locked = d.status === "approved";
    $("split-auto").disabled = $("split-v").disabled = $("split-h").disabled = locked;
    $("approve").disabled = d.status === "approved";
    $("reject").disabled = d.status === "rejected";
    $("reset").disabled = d.status === "pending";
    loadSimilar(d);
  }

  var similarFor = null;
  async function loadSimilar(d) {
    var box = $("similar");
    if (d.status !== "pending") { box.hidden = true; similarFor = null; return; }
    var key = d.id + ":" + d.x + "," + d.y + "," + d.width + "," + d.height;
    if (similarFor === key) return;
    similarFor = key;
    box.hidden = true;
    try {
      var matches = await Api.get("/api/detections/" + d.id + "/similar");
      if (similarFor !== key || !matches.length) return;
      $("similar-list").innerHTML = matches.map(function (m) {
        return '<div class="similar-item">' +
          '<a href="/pins/' + m.pin_code + '" target="_blank"><img src="/media/' + m.thumbnail_path + '" alt=""></a>' +
          '<div><div><strong>' + m.pin_code + "</strong> " + (m.title ? escapeHtml(m.title) : "") + "</div>" +
          '<div class="muted small">' + Math.round(m.score * 100) + "% alike · you have " + m.quantity + "</div>" +
          '<button class="btn small" data-copy="' + m.pin_code + '">Same pin: +1 to ' + m.pin_code + "</button></div></div>";
      }).join("");
      box.hidden = false;
    } catch (err) { /* similarity is optional; ignore */ }
  }
  function escapeHtml(t) { return String(t).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }

  $("similar-list").addEventListener("click", function (e) {
    var b = e.target.closest("[data-copy]"); if (!b) return;
    var d = byId(selectedId); if (!d) return;
    var code = b.getAttribute("data-copy");
    act(async function () {
      var res = await Api.post("/api/detections/" + d.id + "/copy-of/" + code);
      replace(res.detection);
      Toast.show(code + " now has quantity " + res.quantity);
      step(1, true); draw(); showPanel();
    });
  });

  function select(id, opts) {
    opts = opts || {};
    if (opts.additive && selectedId != null && id !== selectedId) {
      if (multi.has(id)) multi.delete(id); else multi.add(id);
    } else {
      selectedId = id;
      multi.clear();
    }
    draw();
    showPanel();
    var d = byId(selectedId);
    if (d && opts.center) centerOn(d);
  }

  function step(delta, onlyPending) {
    if (!detections.length) return;
    var index = detections.findIndex(function (d) { return d.id === selectedId; });
    for (var i = 1; i <= detections.length; i++) {
      var next = detections[(index + delta * i + detections.length * 2) % detections.length];
      if (!onlyPending || next.status === "pending") { select(next.id, { center: true }); return; }
    }
    if (onlyPending) { Toast.show("All boxes on this photo are reviewed 🎉"); }
  }

  function replace(updated) {
    var i = detections.findIndex(function (d) { return d.id === updated.id; });
    if (i >= 0) detections[i] = updated; else detections.push(updated);
  }

  async function reload(selectId) {
    detections = await Api.get("/api/sources/" + SRC.id + "/detections");
    if (selectId !== undefined) selectedId = selectId;
    if (!byId(selectedId)) selectedId = null;
    multi.forEach(function (id) { if (!byId(id)) multi.delete(id); });
    draw(); showPanel();
  }

  // ------------------------------------------------------------- actions
  async function act(fn) {
    try { await fn(); } catch (err) { Toast.error(err.message); }
  }

  function approve() {
    var d = byId(selectedId); if (!d || d.status === "approved") return;
    act(async function () {
      var res = await Api.post("/api/detections/" + d.id + "/approve");
      replace(res.detection);
      Toast.show("Approved as " + res.pin_code);
      step(1, true); draw(); showPanel();
    });
  }
  function reject() {
    var d = byId(selectedId); if (!d || d.status === "rejected") return;
    act(async function () {
      var res = await Api.post("/api/detections/" + d.id + "/reject");
      replace(res.detection);
      step(1, true); draw(); showPanel();
    });
  }
  function reset() {
    var d = byId(selectedId); if (!d || d.status === "pending") return;
    act(async function () { var res = await Api.post("/api/detections/" + d.id + "/reset"); replace(res.detection); draw(); showPanel(); });
  }
  function saveBox(box) {
    var d = byId(selectedId); if (!d) return;
    act(async function () {
      var updated = await Api.put("/api/detections/" + d.id + "/box", box);
      replace(updated); draw(); showPanel();
      if (updated.pin_code) Toast.show("Crop of " + updated.pin_code + " updated");
    });
  }
  function split(modeName) {
    var d = byId(selectedId); if (!d) return;
    act(async function () {
      var res = await Api.post("/api/detections/" + d.id + "/split", { mode: modeName });
      Toast.show("Split into " + res.detections.length + " boxes");
      await reload(res.detections[0].id);
    });
  }
  function merge() {
    if (selectedId == null || multi.size < 1) { Toast.show("Shift+click the other box(es) to merge first"); return; }
    var ids = [selectedId].concat(Array.from(multi));
    act(async function () {
      var res = await Api.post("/api/detections/merge", { detection_ids: ids });
      multi.clear();
      Toast.show("Merged " + ids.length + " boxes");
      await reload(res.detection.id);
    });
  }
  function createBox(box) {
    act(async function () {
      var created = await Api.post("/api/sources/" + SRC.id + "/detections", box);
      detections.push(created);
      setMode("select");
      select(created.id);
      Toast.show("New box added — approve it when it looks right");
    });
  }

  // --------------------------------------------------------- interaction
  var drag = null;     // {kind: "pan"|"move"|"resize", ...}
  var drawing = null;  // {start, box}

  function setMode(m) {
    mode = m;
    $("mode-select").classList.toggle("active", m === "select");
    $("mode-draw").classList.toggle("active", m === "draw");
    viewport.classList.toggle("drawing-mode", m === "draw");
    draw();
  }

  function clampBox(b) {
    var x = Math.max(0, Math.min(SRC.width - 1, b.x));
    var y = Math.max(0, Math.min(SRC.height - 1, b.y));
    var w = Math.max(1, Math.min(SRC.width - x, b.width));
    var h = Math.max(1, Math.min(SRC.height - y, b.height));
    return { x: Math.round(x), y: Math.round(y), width: Math.round(w), height: Math.round(h) };
  }
  function boxFromPoints(a, b) {
    return clampBox({ x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), width: Math.abs(a.x - b.x), height: Math.abs(a.y - b.y) });
  }

  viewport.addEventListener("pointerdown", function (e) {
    if (e.button !== 0) return;
    viewport.focus({ preventScroll: true });
    var p = toImage(e.clientX, e.clientY);
    var target = e.target;
    viewport.setPointerCapture(e.pointerId);

    if (mode === "draw") {
      drawing = { start: p, box: { x: p.x, y: p.y, width: 0, height: 0 } };
      return;
    }
    var handle = target.getAttribute && target.getAttribute("data-handle");
    var group = target.closest && target.closest("g.det");
    if (handle && selectedId != null) {
      var d = byId(selectedId);
      drag = { kind: "resize", handle: handle, orig: Object.assign({}, d), start: p, moved: false };
    } else if (group) {
      var id = Number(group.getAttribute("data-id"));
      if (e.shiftKey) { select(id, { additive: true }); return; }
      if (id !== selectedId) select(id);
      var sel = byId(id);
      drag = { kind: "move", orig: Object.assign({}, sel), start: p, moved: false };
    } else {
      drag = { kind: "pan", sx: e.clientX, sy: e.clientY, tx: view.tx, ty: view.ty, moved: false };
    }
  });

  viewport.addEventListener("pointermove", function (e) {
    if (drawing) {
      drawing.box = boxFromPoints(drawing.start, toImage(e.clientX, e.clientY));
      draw();
      return;
    }
    if (!drag) return;
    if (drag.kind === "pan") {
      view.tx = drag.tx + (e.clientX - drag.sx);
      view.ty = drag.ty + (e.clientY - drag.sy);
      if (Math.abs(e.clientX - drag.sx) + Math.abs(e.clientY - drag.sy) > 3) drag.moved = true;
      applyView();
      return;
    }
    var p = toImage(e.clientX, e.clientY);
    var dx = p.x - drag.start.x, dy = p.y - drag.start.y;
    if (Math.abs(dx) + Math.abs(dy) > screenToImageLength(3)) drag.moved = true;
    if (!drag.moved) return;
    var d = byId(selectedId), o = drag.orig;
    if (drag.kind === "move") {
      Object.assign(d, clampBox({ x: o.x + dx, y: o.y + dy, width: o.width, height: o.height }));
    } else {
      var x1 = o.x, y1 = o.y, x2 = o.x + o.width, y2 = o.y + o.height;
      if (drag.handle.indexOf("n") >= 0) y1 += dy;
      if (drag.handle.indexOf("s") >= 0) y2 += dy;
      if (drag.handle.indexOf("w") >= 0) x1 += dx;
      if (drag.handle.indexOf("e") >= 0) x2 += dx;
      Object.assign(d, boxFromPoints({ x: x1, y: y1 }, { x: x2, y: y2 }));
    }
    draw();
  });

  function endPointer() {
    if (drawing) {
      var box = drawing.box;
      drawing = null;
      draw();
      if (box.width > screenToImageLength(8) && box.height > screenToImageLength(8)) createBox(box);
      return;
    }
    if (!drag) return;
    var finished = drag;
    drag = null;
    if (finished.kind === "pan") {
      if (!finished.moved) { selectedId = null; multi.clear(); draw(); showPanel(); }
      return;
    }
    if (finished.moved) {
      var d = byId(selectedId);
      saveBox({ x: d.x, y: d.y, width: d.width, height: d.height });
    }
  }
  viewport.addEventListener("pointerup", endPointer);
  viewport.addEventListener("pointercancel", endPointer);

  viewport.addEventListener("wheel", function (e) {
    e.preventDefault();
    zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX, e.clientY);
  }, { passive: false });

  document.addEventListener("keydown", function (e) {
    if (e.target.matches("input, textarea, select")) return;
    var key = e.key.toLowerCase();
    var handlers = {
      "a": approve, "r": reject, "u": reset, "m": merge,
      "arrowright": function () { step(1); }, "n": function () { step(1); },
      "arrowleft": function () { step(-1); }, "p": function () { step(-1); },
      "d": function () { setMode("draw"); }, "v": function () { setMode("select"); },
      "escape": function () { if (mode === "draw") setMode("select"); else select(null); },
      "+": function () { zoomAt(1.25); }, "=": function () { zoomAt(1.25); },
      "-": function () { zoomAt(0.8); }, "0": fit
    };
    if (handlers[key]) { e.preventDefault(); handlers[key](); }
  });

  // ------------------------------------------------------------- buttons
  $("approve").onclick = approve;
  $("reject").onclick = reject;
  $("reset").onclick = reset;
  $("merge").onclick = merge;
  $("split-auto").onclick = function () { split("auto"); };
  $("split-v").onclick = function () { split("vertical"); };
  $("split-h").onclick = function () { split("horizontal"); };
  $("prev-det").onclick = function () { step(-1); };
  $("next-det").onclick = function () { step(1); };
  $("mode-select").onclick = function () { setMode("select"); };
  $("mode-draw").onclick = function () { setMode("draw"); };
  $("zoom-in").onclick = function () { zoomAt(1.25); };
  $("zoom-out").onclick = function () { zoomAt(0.8); };
  $("zoom-fit").onclick = fit;
  $("save-box").onclick = function () {
    saveBox(clampBox({ x: +$("box-x").value, y: +$("box-y").value, width: +$("box-w").value, height: +$("box-h").value }));
  };
  $("photo-select").onchange = function () { location.href = "/review/" + this.value; };
  $("page-label").addEventListener("change", function () {
    var value = this.value;
    act(async function () { await Api.post("/api/sources/" + SRC.id + "/label", { label: value }); Toast.show("Page name saved"); });
  });
  $("approve-all").onclick = function () {
    var count = detections.filter(function (d) { return d.status === "pending" && !(d.flags && d.flags.length); }).length;
    if (!count) { Toast.show("No unflagged pending boxes"); return; }
    if (!confirm("Approve " + count + " pending box(es) without warnings? Flagged boxes stay pending.")) return;
    act(async function () {
      $("approve-all").disabled = true;
      try {
        var res = await Api.post("/api/sources/" + SRC.id + "/approve-all");
        Toast.show("Approved " + res.approved.length + " pins");
        await reload();
      } finally { $("approve-all").disabled = false; }
    });
  };
  $("redetect").onclick = function () {
    if (!confirm("Run the detector again on this photo? Pending automatic boxes are replaced; reviewed and hand-drawn boxes are kept.")) return;
    act(async function () {
      var res = await Api.post("/api/sources/" + SRC.id + "/redetect");
      Toast.show(res.added + " new candidate(s)");
      await reload();
    });
  };
  $("perspective").onclick = function () {
    var modal = $("perspective-modal");
    modal.hidden = false;
    $("persp-error").hidden = true;
    var base = "/images/" + SRC.id + "/perspective.jpg";
    $("persp-outline").src = base + "?view=outline";
    $("persp-corrected").src = base + "?view=corrected";
    $("persp-corrected").onerror = function () { $("persp-error").textContent = "The page edges could not be detected on this photo."; $("persp-error").hidden = false; };
  };
  document.querySelectorAll("[data-close]").forEach(function (b) { b.onclick = function () { b.closest(".modal").hidden = true; }; });

  // ---------------------------------------------------------------- start
  setMode("select");
  function start() {
    fit();
    var firstPending = detections.find(function (d) { return d.status === "pending"; });
    if (firstPending) select(firstPending.id); else showPanel();
  }
  if (photo.complete && photo.naturalWidth) start(); else photo.addEventListener("load", start);
  window.addEventListener("resize", function () { fit(); });
})();
