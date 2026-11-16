// data/metrics.json 을 읽어 data-m 요소의 값을 갱신한다. 실패하면 HTML 기본값이 그대로 보인다.
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
}).catch(function () { /* 기본값 유지 */ });
