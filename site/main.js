// 1) data/metrics.json 을 읽어 data-m 요소와 그래프 값을 갱신한다. 실패하면 HTML 기본값이 그대로 보인다.
fetch('data/metrics.json').then(function (r) {
  if (!r.ok) throw new Error(r.status);
  return r.json();
}).then(function (d) {
  document.querySelectorAll('[data-m]').forEach(function (el) {
    var m = d[el.getAttribute('data-m')];
    if (m && typeof m.value !== 'object') el.textContent = m.value;
  });
  var n = d.attendance_note;
  if (n) {
    var a = document.getElementById('att-date'), b = document.getElementById('att-pending');
    if (a) a.textContent = n.value['기준일'];
    if (b) b.textContent = n.value['확정 전 일수'];
  }
  var rate = d.attendance_rate;
  if (rate) document.querySelectorAll('.ring').forEach(function (el) { el.style.setProperty('--v', rate.value); });
  var days = d.ritual_record_days, bars = document.querySelectorAll('.bar');
  if (days && days.value && bars.length === 2) {
    [d.ritual_morning_count, d.ritual_wrapup_count].forEach(function (m, i) {
      if (m) bars[i].style.setProperty('--v', Math.min(100, m.value / days.value * 100));
    });
  }
}).catch(function () { /* 기본값 유지 */ });

// 2) 논문 697 flow 점 격자(41x17). 392개 색칠. 값은 논문(T10) 기준.
(function () {
  document.querySelectorAll('.flow-dots').forEach(function (box) {
    var f = document.createDocumentFragment();
    for (var i = 0; i < 697; i++) {
      var d = document.createElement('i');
      if (i < 392) d.className = 'on';
      f.appendChild(d);
    }
    box.appendChild(f);
    box.parentNode.classList.add('has-dots');
  });
})();

// 3) 화면에 들어오면 한 번만 등장 효과. 지원하지 않으면 즉시 표시.
(function () {
  var els = document.querySelectorAll('.reveal');
  if (!('IntersectionObserver' in window)) {
    els.forEach(function (e) { e.classList.add('in'); });
    return;
  }
  var fired = false;
  function all() { els.forEach(function (e) { e.classList.add('in'); }); }
  // 관찰자가 동작하지 않는 환경(백그라운드·인쇄 등)에서도 내용이 숨겨지지 않게 하는 안전장치
  setTimeout(function () { if (!fired) all(); }, 2500);
  window.addEventListener('beforeprint', all);
  var io = new IntersectionObserver(function (list) {
    fired = true;
    list.forEach(function (x) {
      if (x.isIntersecting) { x.target.classList.add('in'); io.unobserve(x.target); }
    });
  }, { threshold: 0.15 });
  els.forEach(function (e) { io.observe(e); });
})();
