(function () {
  var f = document.querySelector("footer[data-collected]");
  if (!f) return;
  var H = 36e5, n = Date.now(), c = Date.parse(f.dataset.collected), b = Date.parse(f.dataset.built);
  if (isNaN(c) || isNaN(b) || Math.abs(n - b) > 366 * 24 * H || n - c <= 48 * H) return;
  var p = document.createElement("p"), m = document.getElementById("main");
  p.className = "notice";
  p.setAttribute("role", "status");
  p.textContent = "This page was last updated " + f.dataset.collected.slice(0, 10) +
    ". Automated collection or publishing may have stopped.";
  m.insertBefore(p, m.firstChild);
})();
