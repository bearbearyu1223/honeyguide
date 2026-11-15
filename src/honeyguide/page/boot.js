/* Theme and contents rail before first paint, so the page never flashes the wrong theme or width. */
(function () {
  try {
    var d = document.documentElement, t = localStorage.getItem("honeyguide.theme");
    d.dataset.theme = t || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    if (localStorage.getItem("honeyguide.rail") === "1") d.classList.add("rail");
    var w = parseInt(localStorage.getItem("honeyguide.panelWidth"), 10);
    if (w >= 320 && w <= 720) d.style.setProperty("--pw-want", w + "px");
  } catch (e) { /* storage off: defaults */ }
})();
