// Övningsredigeraren: visar rätt delar av formuläret och hämtar förhandsvisningen. Formuläret fungerar även utan detta
// (då visas alla delar och servern väljer utifrån typen).
(function () {
  var form = document.getElementById('exform');
  if (!form) return;
  var topics = JSON.parse(form.dataset.topics || '{}');
  var examples = JSON.parse(form.dataset.examples || '{}');
  var $ = function (id) { return document.getElementById(id); };

  // Flerval eller fritext
  function showType() {
    var t = (form.querySelector('input[name=type]:checked') || {}).value;
    $('mcbox').hidden = t !== 'mc';
    $('textbox').hidden = t !== 'text';
  }
  form.querySelectorAll('input[name=type]').forEach(function (r) { r.addEventListener('change', showType); });
  showType();

  // Ämne: nytt ämne och områdesförslag
  var subject = $('subject');
  function showSubject() {
    $('newsubjectbox').hidden = subject.value !== '__ny__';
    var list = $('topiclist');
    list.innerHTML = '';
    (topics[subject.value] || []).forEach(function (t) {
      var o = document.createElement('option');
      o.value = t;
      list.appendChild(o);
    });
  }
  subject.addEventListener('change', showSubject);

  // Alternativ 5 och 6 visas först när man ber om dem (eller om de är ifyllda)
  var extras = form.querySelectorAll('.optrow.extra');
  var more = $('moreopts');
  if (extras.length) {
    more.hidden = false;
    more.addEventListener('click', function () {
      var next = form.querySelector('.optrow.extra');
      if (next) { next.classList.remove('extra'); next.querySelector('input[name=option]').focus(); }
      if (!form.querySelector('.optrow.extra')) more.hidden = true;
    });
  }

  // Diagram: välj en typ så fylls en mall i (om rutan är tom eller bara innehåller en oförändrad mall)
  var dtype = $('diagram_type'), dtext = $('diagram');
  function isTemplate(text) {
    if (!text.trim()) return true;
    try {
      var cur = JSON.stringify(JSON.parse(text));
      return Object.keys(examples).some(function (k) { return JSON.stringify(examples[k]) === cur; });
    } catch (e) { return false; }
  }
  dtype.addEventListener('change', function () {
    if (!isTemplate(dtext.value)) {
      if (!window.confirm('Ersätta inställningarna med mallen för den här diagramtypen?')) return;
    }
    if (dtype.value && examples[dtype.value]) {
      dtext.value = JSON.stringify(examples[dtype.value], null, 2);
      $('diagrambox').hidden = false;
    } else {
      dtext.value = '';
      $('diagrambox').hidden = true;
    }
    preview();
  });

  // Förhandsvisning
  function preview() {
    var body = $('previewbody');
    var data = new FormData(form);
    data.delete('image_file');   // filer skickas inte med förhandsvisningen
    fetch('/admin/exercises/preview', { method: 'POST', body: data, credentials: 'same-origin' })
      .then(function (r) { return r.text(); })
      .then(function (html) { body.innerHTML = html; })
      .catch(function () { body.textContent = 'Förhandsvisningen gick inte att hämta.'; });
  }
  $('previewbtn').addEventListener('click', function () {
    preview();
    $('preview').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  });
})();
