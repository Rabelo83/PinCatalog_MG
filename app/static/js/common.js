/* Shared helpers: JSON API calls and toast messages. */
(function () {
  "use strict";

  async function request(method, url, body) {
    var options = { method: method, headers: {} };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    var response = await fetch(url, options);
    var text = await response.text();
    var data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = text; }
    if (!response.ok) {
      var message = (data && data.detail) ? data.detail : (typeof data === "string" && data ? data : response.statusText);
      if (Array.isArray(message)) message = message.map(function (m) { return m.msg; }).join("; ");
      throw new Error(message || ("Request failed (" + response.status + ")"));
    }
    return data;
  }

  window.Api = {
    get: function (url) { return request("GET", url); },
    post: function (url, body) { return request("POST", url, body === undefined ? {} : body); },
    put: function (url, body) { return request("PUT", url, body); }
  };

  var timer = null;
  function show(message, isError) {
    var toast = document.getElementById("toast");
    if (!toast) { alert(message); return; }
    toast.textContent = message;
    toast.className = "toast visible" + (isError ? " error" : "");
    clearTimeout(timer);
    timer = setTimeout(function () { toast.className = "toast"; }, isError ? 6000 : 2500);
  }
  window.Toast = { show: function (m) { show(m, false); }, error: function (m) { show(m, true); } };
})();
