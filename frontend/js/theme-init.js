// Runs before first paint (classic script in <head>) so a stored theme never flashes.
try {
  var t = localStorage.getItem("pivitals-theme");
  if (t === "dark" || t === "light") document.documentElement.setAttribute("data-theme", t);
} catch (e) {}
