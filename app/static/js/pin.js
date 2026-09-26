/* Pin detail page: save metadata, show on original, transparent PNG. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var form = $("pin-form");

  form.addEventListener("submit", async function (e) {
    e.preventDefault();
    var f = form.elements;
    var body = {
      title: f.title.value,
      description: f.description.value,
      category: f.category.value,
      subcategory: f.subcategory.value,
      tags: f.tags.value.split(",").map(function (t) { return t.trim(); }).filter(Boolean),
      notes: f.notes.value,
      quantity: f.quantity.value === "" ? null : parseInt(f.quantity.value, 10)
    };
    ["purchase_price", "selling_price"].forEach(function (name) {
      if (f[name].value === "") body["clear_" + name] = true;
      else body[name] = parseFloat(f[name].value);
    });
    try {
      await Api.put("/api/pins/" + encodeURIComponent(window.PIN_CODE), body);
      $("save-state").textContent = "Saved ✓";
      Toast.show("Saved");
    } catch (err) { Toast.error(err.message); }
  });
  form.addEventListener("input", function () { $("save-state").textContent = "Unsaved changes"; });

  document.querySelectorAll(".image-tabs .tab").forEach(function (tab) {
    tab.onclick = function () {
      document.querySelectorAll(".image-tabs .tab").forEach(function (t) { t.classList.remove("active"); });
      tab.classList.add("active");
      $("big-image").src = tab.getAttribute("data-src");
    };
  });

  $("show-original").onclick = function () { $("original-modal").hidden = false; };
  document.querySelectorAll("[data-close]").forEach(function (b) { b.onclick = function () { b.closest(".modal").hidden = true; }; });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") document.querySelectorAll(".modal").forEach(function (m) { m.hidden = true; }); });

  var transparentBtn = $("make-transparent");
  if (transparentBtn) {
    transparentBtn.onclick = async function () {
      transparentBtn.disabled = true;
      transparentBtn.textContent = "Working…";
      try {
        await Api.post("/api/pins/" + encodeURIComponent(window.PIN_CODE) + "/transparent");
        location.reload();
      } catch (err) {
        Toast.error(err.message);
        transparentBtn.disabled = false;
        transparentBtn.textContent = "Make transparent PNG";
      }
    };
  }
})();
