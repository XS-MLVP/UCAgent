/* Raw preview needs HTTP/Wasm isolation; signed links preserve their original token. */
(() => {
  const requested = new URL(location.href).searchParams.get('id');
  const links = [...document.querySelectorAll('[data-wave-id]')];
  if (location.protocol === 'file:') {
    document.getElementById('http-required').hidden = false;
    links.forEach(link => link.addEventListener('click', event => {
      event.preventDefault();
      document.getElementById('http-required').hidden = false;
    }));
    return;
  }
  const selected = links.find(link => link.dataset.waveId === requested);
  if (selected) location.replace(selected.href);
})();
