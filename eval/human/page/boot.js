/* Theme before first paint (the same rule as the map page: a saved choice, else the system's). */
(function () {
  try {
    var d = document.documentElement, t = localStorage.getItem("hg-eval.theme");
    d.dataset.theme = t || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  } catch (e) { document.documentElement.dataset.theme = "light"; }
})();
