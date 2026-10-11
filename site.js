/* mirror-leech-telegram-bot-fuse site: copy buttons + reveal on scroll. Page works without JS. */
(function () {
  'use strict';
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;

  // copy buttons on code blocks
  document.querySelectorAll('.codeblock').forEach(function (box) {
    var pre = box.querySelector('pre');
    if (!pre || !navigator.clipboard) return;
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'copy';
    b.textContent = 'Copy';
    b.setAttribute('aria-label', 'Copy code to clipboard');
    b.addEventListener('click', function () {
      navigator.clipboard.writeText(pre.innerText.replace(/\n$/, '')).then(function () {
        b.textContent = 'Copied';
        setTimeout(function () { b.textContent = 'Copy'; }, 1600);
      }, function () {
        b.textContent = 'Press Ctrl+C';
        setTimeout(function () { b.textContent = 'Copy'; }, 1600);
      });
    });
    box.appendChild(b);
  });

  // reveal on scroll
  var items = document.querySelectorAll('.rv, .bars, .chart');
  if (reduce || !('IntersectionObserver' in window)) {
    items.forEach(function (el) { el.classList.add('in'); });
    return;
  }
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
    });
  }, { threshold: 0.12, rootMargin: '0px 0px -6% 0px' });
  items.forEach(function (el) { io.observe(el); });
})();
