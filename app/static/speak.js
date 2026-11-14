/* Uppläsning med webbläsarens inbyggda röst. Varje knapp (button.speak) bär sin text som JSON i data-speak:
   [{"t": "text", "l": "en-GB", "n": "engelsk"}, ...]. Inget spelas av sig självt, bara när man trycker. */
(function () {
  "use strict";
  var synth = window.speechSynthesis;
  var buttons = document.querySelectorAll("button.speak");
  if (!synth || !window.SpeechSynthesisUtterance || !buttons.length) return;   // inget stöd: knapparna förblir dolda

  var current = null;        // knappen som läser just nu

  function message(text) {
    var el = document.querySelector(".speakmsg");
    if (!el) return;
    el.textContent = text;
    el.hidden = !text;
  }

  // Bästa rösten för språkkoden: exakt språk och land först, annars något annat land med samma språk
  function pickVoice(lang) {
    var voices = synth.getVoices() || [];
    var wanted = lang.toLowerCase().replace("_", "-");
    var base = wanted.split("-")[0];
    var exact = null, same = null;
    for (var i = 0; i < voices.length; i++) {
      var v = (voices[i].lang || "").toLowerCase().replace("_", "-");
      if (v === wanted && !exact) exact = voices[i];
      else if (v.split("-")[0] === base && !same) same = voices[i];
    }
    return { voice: exact || same, haveVoices: voices.length > 0 };
  }

  // Långa texter delas vid meningsslut, annars klipper Chrome av uppläsningen efter en stund
  function chunks(text) {
    if (text.length < 160) return [text];
    return text.match(/[^.!?]+[.!?]*\s*/g) || [text];
  }

  function done(btn) {
    btn.classList.remove("speaking");
    btn.removeAttribute("aria-pressed");
    if (current === btn) current = null;
  }

  function stop() {
    synth.cancel();
    if (current) done(current);
  }

  function speak(btn) {
    var segments;
    try { segments = JSON.parse(btn.getAttribute("data-speak")); } catch (e) { return; }
    if (!segments || !segments.length) return;
    var wasThis = current === btn;
    stop();
    if (wasThis) return;                     // ett tryck till på samma knapp stoppar

    message("");
    var queue = [];
    for (var i = 0; i < segments.length; i++) {
      var found = pickVoice(segments[i].l);
      if (found.haveVoices && !found.voice) {
        message("Den här enheten har ingen " + (segments[i].n || "") + " röst installerad, så det går inte att läsa upp här.");
        return;
      }
      var parts = chunks(segments[i].t);
      for (var j = 0; j < parts.length; j++) {
        var u = new SpeechSynthesisUtterance(parts[j]);
        u.lang = segments[i].l;
        if (found.voice) u.voice = found.voice;
        u.rate = 0.9;                        // lite lugnare än vanligt, bra när man lyssnar efter uttalet
        queue.push(u);
      }
    }
    var last = queue[queue.length - 1];
    last.onend = last.onerror = function () { done(btn); };
    current = btn;
    btn.classList.add("speaking");
    btn.setAttribute("aria-pressed", "true");
    // Allt köas direkt i klickhändelsen. Safari på iPhone släpper bara igenom tal som startar av ett tryck.
    for (var k = 0; k < queue.length; k++) synth.speak(queue[k]);
  }

  for (var b = 0; b < buttons.length; b++) {
    buttons[b].hidden = false;
    buttons[b].addEventListener("click", function (ev) { ev.preventDefault(); speak(ev.currentTarget); });
  }
  window.addEventListener("pagehide", function () { synth.cancel(); });   // inget som pratar vidare på nästa sida
})();
