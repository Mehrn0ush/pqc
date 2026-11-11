/* Optional enhancement only: filtering and sorting of the readiness matrix.
   All content is already in the HTML; nothing here is required to read it. */
(function () {
  "use strict";
  var table = document.getElementById("matrix");
  if (!table || !table.tBodies.length) return;
  var body = table.tBodies[0];
  var rows = Array.prototype.slice.call(body.rows);
  var host = document.getElementById("matrix-controls");
  if (!host) return;

  function select(id, label, options) {
    var l = document.createElement("label");
    l.setAttribute("for", id);
    l.textContent = label;
    var s = document.createElement("select");
    s.id = id;
    options.forEach(function (o) {
      var opt = document.createElement("option");
      opt.value = o[0];
      opt.textContent = o[1];
      s.appendChild(opt);
    });
    l.appendChild(s);
    host.appendChild(l);
    return s;
  }

  var kind = select("f-kind", "Kind", [["", "All kinds"], ["library", "Library"], ["runtime", "Runtime"], ["protocol tool", "Protocol tool"]]);
  var status = select("f-status", "Has a claim with status", [["", "Any status"], ["supported", "Supported"], ["experimental", "Experimental"], ["planned", "Planned"], ["not-supported", "Not supported"], ["no-statement-found", "No statement found"], ["not-checked", "Not checked"]]);
  var sort = select("f-sort", "Sort by", [["name", "Name (A to Z)"], ["released", "Latest release date (newest first)"]]);
  var count = document.createElement("p");
  count.setAttribute("role", "status");
  count.className = "provenance";
  host.appendChild(count);

  function apply() {
    var visible = 0;
    rows.forEach(function (r) {
      var okKind = !kind.value || r.getAttribute("data-kind") === kind.value;
      var okStatus = !status.value || (r.getAttribute("data-statuses") || "").split(" ").indexOf(status.value) !== -1;
      var show = okKind && okStatus;
      r.hidden = !show;
      if (show) visible++;
    });
    var ordered = rows.slice().sort(function (a, b) {
      if (sort.value === "released") {
        return (b.getAttribute("data-released") || "").localeCompare(a.getAttribute("data-released") || "");
      }
      return a.getAttribute("data-name").localeCompare(b.getAttribute("data-name"));
    });
    ordered.forEach(function (r) { body.appendChild(r); });
    count.textContent = "Showing " + visible + " of " + rows.length + " projects.";
  }
  [kind, status, sort].forEach(function (s) { s.addEventListener("change", apply); });
  apply();
})();
