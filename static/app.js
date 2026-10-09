/* Budget Tracker frontend: vanilla JS + fetch. */

const $ = (id) => document.getElementById(id);

const fmt = (n) =>
  (n < 0 ? "-" : "") + "$" + Math.abs(n).toFixed(2);

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = body.detail;
    const msg = Array.isArray(detail)
      ? detail.map((d) => d.msg).join("; ")
      : detail || res.statusText;
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

async function refresh() {
  const [txns, summary] = await Promise.all([
    api("/api/transactions?limit=100"),
    api("/api/summary"),
  ]);
  renderTransactions(txns);
  renderSummary(summary);
}

function renderTransactions(txns) {
  const rows = $("txn-rows");
  if (!txns.length) {
    rows.innerHTML = '<tr><td colspan="5" class="muted">No transactions yet.</td></tr>';
    return;
  }
  rows.innerHTML = txns.map((t) => `
    <tr>
      <td>${t.date}</td>
      <td>${escapeHtml(t.description)}</td>
      <td><span class="tag">${escapeHtml(t.category)}</span></td>
      <td class="num ${t.amount < 0 ? "neg" : "pos"}">${fmt(t.amount)}</td>
      <td><button class="del" data-id="${t.id}" title="Delete">×</button></td>
    </tr>`).join("");
  rows.querySelectorAll(".del").forEach((btn) =>
    btn.addEventListener("click", async () => {
      await api(`/api/transactions/${btn.dataset.id}`, { method: "DELETE" });
      refresh();
    })
  );
}

function renderSummary(summary) {
  const cards = $("month-cards");
  const bars = $("cat-bars");
  if (!summary.length) {
    cards.innerHTML = '<p class="muted">No data yet.</p>';
    bars.innerHTML = "";
    return;
  }
  const m = summary[0]; // newest month
  cards.innerHTML = `
    <div class="stat"><div class="label">${m.month} spent</div>
      <div class="value neg">${fmt(-m.spending)}</div></div>
    <div class="stat"><div class="label">Income</div>
      <div class="value pos">${fmt(m.income)}</div></div>
    <div class="stat"><div class="label">Net</div>
      <div class="value ${m.net < 0 ? "neg" : "pos"}">${fmt(m.net)}</div></div>`;
  bars.innerHTML = m.by_category.map((c) => `
    <div class="bar-row">
      <span>${escapeHtml(c.category)}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${c.share}%"></div></div>
      <span class="num">${fmt(-c.total)} (${c.share}%)</span>
    </div>`).join("");
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

$("txn-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = $("form-error");
  err.hidden = true;
  try {
    await api("/api/transactions", {
      method: "POST",
      body: JSON.stringify({
        date: $("f-date").value,
        description: $("f-desc").value,
        amount: parseFloat($("f-amount").value),
        category: $("f-cat").value,
      }),
    });
    e.target.reset();
    $("f-date").valueAsDate = new Date();
    refresh();
  } catch (ex) {
    err.textContent = ex.message;
    err.hidden = false;
  }
});

$("f-date").valueAsDate = new Date();
refresh().catch((ex) => {
  $("txn-rows").innerHTML =
    `<tr><td colspan="5" class="error">Could not reach the API: ${escapeHtml(ex.message)}</td></tr>`;
});
