/* Filter only derived report rows; records and execution results are never edited. */
(() => {
  const search = document.getElementById('report-search');
  const filter = document.getElementById('case-filter');
  if (!search || !filter) return;
  const rows = [...document.querySelectorAll('#case-table tbody tr')];
  function apply() {
    const query = search.value.trim().toLowerCase();
    const bugs = [...document.querySelectorAll('#bug-table tbody tr')];
    bugs.forEach(row => row.hidden = !row.dataset.search.toLowerCase().includes(query));
    document.getElementById('bug-empty').hidden = bugs.some(row => !row.hidden);
    rows.forEach(row => row.hidden = !(filter.value === 'all' || row.dataset.category === filter.value)
      || !row.dataset.search.toLowerCase().includes(query));
    const count = rows.filter(row => !row.hidden).length;
    document.getElementById('case-count').textContent = `${count} / ${rows.length}`;
    document.getElementById('case-empty').hidden = count !== 0;
  }
  search.addEventListener('input', apply);
  filter.addEventListener('change', apply);
})();
