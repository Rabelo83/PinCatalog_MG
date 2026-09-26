/* Dashboard: start processing, show progress, run exports. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };

  function renderStatus(status) {
    var box = $("process-status");
    box.hidden = false;
    if (status.running) {
      box.textContent = status.total
        ? "Processing " + status.index + " of " + status.total + ": " + (status.current || "") + " …"
        : "Starting …";
    } else if (status.error) {
      box.textContent = "Processing stopped: " + status.error;
    } else {
      box.textContent = "Finished.";
    }
    var list = $("process-results");
    list.innerHTML = "";
    (status.results || []).forEach(function (r) {
      var li = document.createElement("li");
      li.className = "result-" + r.status;
      var text = r.filename + " — ";
      if (r.status === "imported") text += "detected candidates: " + r.detections + " (pending review)";
      else if (r.status === "duplicate") text += "already in the system. " + r.message;
      else text += "error: " + r.message;
      li.textContent = text;
      list.appendChild(li);
    });
  }

  async function poll() {
    try {
      var status = await Api.get("/api/process/status");
      renderStatus(status);
      if (status.running) { setTimeout(poll, 1000); return; }
      $("process-btn").disabled = false;
      var total = (status.results || []).reduce(function (n, r) { return n + (r.detections || 0); }, 0);
      Toast.show("Complete. " + total + " candidates awaiting review.");
      setTimeout(function () { location.reload(); }, 2500);
    } catch (err) {
      Toast.error(err.message);
      $("process-btn").disabled = false;
    }
  }

  $("process-btn").onclick = async function () {
    this.disabled = true;
    try {
      var res = await Api.post("/api/process");
      if (!res.waiting) { Toast.show("No new photos in the input folder."); this.disabled = false; return; }
      if (!res.started) Toast.show("Processing is already running…");
      poll();
    } catch (err) { Toast.error(err.message); this.disabled = false; }
  };

  $("export-btn").onclick = async function () {
    var button = this;
    button.disabled = true;
    $("export-panel").hidden = false;
    $("export-status").textContent = "Exporting…";
    try {
      var res = await Api.post("/api/export", { formats: ["csv", "json", "html"] });
      var html = "<p>Exported <strong>" + res.pin_count + "</strong> pins.</p><ul>" +
        '<li>CSV: <a href="/api/export/download/csv">data/' + res.csv + "</a></li>" +
        '<li>JSON: <a href="/api/export/download/json">data/' + res.json + "</a></li>" +
        '<li>HTML gallery: <a href="/api/export/catalog/index.html" target="_blank">data/' + res.html + "/index.html</a></li>";
      if (res.published) html += "<li>GitHub Pages copy: <code>" + res.published + "</code> — commit and push it to update the website.</li>";
      html += "</ul>";
      (res.warnings || []).forEach(function (w) { html += '<p class="error">' + w.replace(/</g, "&lt;") + "</p>"; });
      $("export-status").innerHTML = html;
    } catch (err) {
      $("export-status").textContent = "Export failed: " + err.message;
    } finally { button.disabled = false; }
  };

  if (window.PROCESSING_RUNNING) { $("process-btn").disabled = true; poll(); }
})();
