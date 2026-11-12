(function () {
  var btn = document.getElementById('copyprompt');
  var box = document.getElementById('aiprompt');
  var done = document.getElementById('copied');
  if (!btn || !box) return;
  btn.addEventListener('click', function () {
    box.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    if (!ok && navigator.clipboard) { navigator.clipboard.writeText(box.value); ok = true; }
    if (done) done.hidden = !ok;
  });
})();
