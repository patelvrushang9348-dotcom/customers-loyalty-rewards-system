import { $, api, esc, say, fmtDate } from "/static/common.js";

const TABS = ["Overview", "Batches", "Products", "Rewards", "Claims", "Customers", "Fraud log"];
let current = "Overview";
const view = $("#view");
const pill = (s) => `<span class="pill ${esc(s)}">${esc(s)}</span>`;

$("#login-form").onsubmit = async (e) => {
  e.preventDefault();
  try { await api("/api/admin/login", "POST", { username: $("#u").value, password: $("#p").value }); start(); }
  catch (err) { say($("#login-msg"), err.message, "bad"); }
};
$("#logout").onclick = async () => { await api("/api/admin/logout", "POST", {}); location.reload(); };

function start() {
  $("#login").classList.add("hidden"); $("#dash").classList.remove("hidden"); $("#logout").classList.remove("hidden");
  $("#tabs").innerHTML = TABS.map((t) => `<button role="tab" data-t="${t}" aria-selected="${t === current}">${t}</button>`).join("");
  render();
}
$("#tabs").onclick = (e) => { if (e.target.dataset.t) { current = e.target.dataset.t; start(); } };
api("/api/admin/me").then(start).catch(() => {});

const table = (head, rows, empty = "Nothing here yet.") =>
  `<div class="scroll"><table><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${
    rows.join("") || `<tr><td colspan="${head.length}" class="muted">${empty}</td></tr>`}</tbody></table></div>`;

async function render() {
  view.textContent = "Loading…";
  try { await ({ Overview, Batches, Products, Rewards, Claims, Customers, "Fraud log": Fraud })[current](); }
  catch (err) { if (err.status === 401) location.reload(); else view.innerHTML = `<p class="msg bad">${esc(err.message)}</p>`; }
}

// ------------------------------------------------------------ overview
async function Overview() {
  const s = await api("/api/admin/stats");
  const stat = (l, v, warn) => `<div class="stat ${warn ? "warn" : ""}"><div class="v">${v}</div><div class="muted">${l}</div></div>`;
  const max = Math.max(1, ...s.daily_redemptions.map((d) => d.n));
  view.innerHTML = `
  <div class="stats">
    ${stat("Codes printed", s.codes_generated)}${stat("Codes redeemed", s.codes_redeemed)}
    ${stat("Redemption rate", (s.redemption_rate * 100).toFixed(1) + "%")}${stat("Customers", s.customers)}
    ${stat("Points issued", s.points_issued)}${stat("Points outstanding (liability)", s.points_outstanding)}
    ${stat("Claims to fulfil", s.pending_claims, s.pending_claims > 0)}
    ${stat("Failed code attempts (24h)", s.failed_attempts_24h, s.failed_attempts_24h > 10)}
    ${stat("Lockouts (24h)", s.lockouts_24h, s.lockouts_24h > 0)}${stat("Suspended customers", s.suspended_customers, s.suspended_customers > 0)}
  </div>
  <div class="panel" style="margin-top:1.1rem"><h2>Redemptions, last 14 days</h2>
    ${s.daily_redemptions.length ? `<div class="bars" style="margin-bottom:1.6rem">${s.daily_redemptions.map((d) =>
      `<div style="height:${Math.max(6, (d.n / max) * 100)}%" title="${esc(d.day)}: ${d.n}"><span>${esc(d.day.slice(5))}</span></div>`).join("")}</div>` : '<p class="muted">No redemptions yet.</p>'}
  </div>
  <div class="panel"><h2>By product</h2>${table(["Product", "Printed", "Redeemed", "Voided"],
    s.per_product.map((p) => `<tr><td>${esc(p.name)}</td><td class="num">${p.generated}</td><td class="num">${p.redeemed}</td><td class="num">${p.voided}</td></tr>`))}</div>`;
}

// ------------------------------------------------------------ batches
async function Batches() {
  const [products, batches] = await Promise.all([api("/api/admin/products"), api("/api/admin/batches")]);
  const active = products.filter((p) => p.active);
  view.innerHTML = `
  <div class="panel"><h2>Generate a batch of codes</h2>
    <form id="bf" class="row">
      <div><label for="bp">Product</label><select id="bp" required>${active.map((p) => `<option value="${p.id}">${esc(p.name)} (${p.points} pts)</option>`).join("")}</select></div>
      <div><label for="bq">Quantity</label><input id="bq" type="number" min="1" max="10000" value="100" required></div>
      <div><label for="bd">Valid for (days)</label><input id="bd" type="number" min="1" max="3650" value="365" required></div>
      <div><label for="bn">Note</label><input id="bn" maxlength="200" placeholder="e.g. Line 2, 9 Nov"></div>
      <button type="submit" ${active.length ? "" : "disabled"}>Generate</button></form>
    <div id="bmsg" class="msg" role="status">${active.length ? "" : "Create a product first."}</div>
    <p class="muted">Codes are shown <b>once</b>. Only hashes are stored, so download the CSV straight away and send it to your printer.</p>
  </div>
  <div class="panel"><h2>Batches</h2>${table(["#", "Product", "Printed", "Redeemed", "Voided", "Expires", "Status", "Note", ""],
    batches.map((b) => `<tr><td>${b.id}</td><td>${esc(b.product)}</td><td class="num">${b.quantity}</td><td class="num">${b.redeemed}</td><td class="num">${b.voided}</td>
      <td>${fmtDate(b.expires_at)}</td><td>${pill(b.status)}</td><td>${esc(b.note)}</td>
      <td>${b.status === "active" ? `<button class="danger small" data-void="${b.id}">Void unused</button>` : ""}</td></tr>`))}</div>`;

  $("#bf").onsubmit = async (e) => {
    e.preventDefault();
    try {
      const r = await api("/api/admin/batches", "POST", { product_id: +$("#bp").value, quantity: +$("#bq").value, valid_days: +$("#bd").value, note: $("#bn").value });
      const csv = "code,product,points,batch_id\n" + r.codes.map((c) => `${c},"${r.product.replace(/"/g, '""')}",${r.points},${r.batch_id}`).join("\n");
      const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })), download: `batch-${r.batch_id}-codes.csv` });
      document.body.append(a); a.click(); a.remove();
      await Batches();
      say($("#bmsg"), `Batch #${r.batch_id}: ${r.codes.length} codes generated. CSV downloaded (it cannot be downloaded again).`, "ok");
    } catch (err) { say($("#bmsg"), err.message, "bad"); }
  };
  view.onclick = async (e) => {
    const id = e.target.dataset?.void;
    if (!id || !confirm(`Void all unused codes in batch #${id}? This cannot be undone.`)) return;
    try { const r = await api(`/api/admin/batches/${id}/void`, "POST", {}); await Batches(); say($("#bmsg"), `${r.voided_codes} codes voided.`, "ok"); }
    catch (err) { say($("#bmsg"), err.message, "bad"); }
  };
}

// ------------------------------------------------------------ products
async function Products() {
  const rows = await api("/api/admin/products");
  view.innerHTML = `
  <div class="panel"><h2>Add a product</h2><form id="pf" class="row">
    <div><label for="pn">Name</label><input id="pn" required maxlength="120"></div>
    <div><label for="ps">SKU</label><input id="ps" required maxlength="60"></div>
    <div><label for="pp">Points per box</label><input id="pp" type="number" min="1" max="100000" required></div>
    <button type="submit">Add</button></form><div id="pmsg" class="msg" role="status"></div></div>
  <div class="panel"><h2>Products</h2>${table(["Name", "SKU", "Points", "Status", ""],
    rows.map((p) => `<tr><td>${esc(p.name)}</td><td>${esc(p.sku)}</td><td class="num">${p.points}</td><td>${pill(p.active ? "active" : "voided")}</td>
    <td><button class="ghost small" data-toggle="${p.id}" data-active="${p.active}">${p.active ? "Deactivate" : "Activate"}</button></td></tr>`))}</div>`;
  $("#pf").onsubmit = async (e) => {
    e.preventDefault();
    try { await api("/api/admin/products", "POST", { name: $("#pn").value, sku: $("#ps").value, points: +$("#pp").value }); await Products(); }
    catch (err) { say($("#pmsg"), err.message, "bad"); }
  };
  view.onclick = async (e) => {
    const id = e.target.dataset?.toggle; if (!id) return;
    await api(`/api/admin/products/${id}`, "PUT", { active: e.target.dataset.active === "1" ? 0 : 1 }); await Products();
  };
}

// ------------------------------------------------------------ rewards
async function Rewards() {
  const rows = await api("/api/admin/rewards");
  view.innerHTML = `
  <div class="panel"><h2>Add a reward</h2><form id="rf" class="row">
    <div><label for="rn">Name</label><input id="rn" required maxlength="120"></div>
    <div><label for="rd">Description</label><input id="rd" maxlength="500"></div>
    <div><label for="rc">Points cost</label><input id="rc" type="number" min="1" required></div>
    <div><label for="rs">Stock (blank = unlimited)</label><input id="rs" type="number" min="0"></div>
    <button type="submit">Add</button></form><div id="rmsg" class="msg" role="status"></div></div>
  <div class="panel"><h2>Catalogue</h2>${table(["Name", "Cost", "Stock", "Status", ""],
    rows.map((r) => `<tr><td>${esc(r.name)}<br><span class="muted">${esc(r.description)}</span></td><td class="num">${r.points_cost}</td>
    <td class="num">${r.stock ?? "∞"}</td><td>${pill(r.active ? "active" : "voided")}</td>
    <td><button class="ghost small" data-toggle="${r.id}" data-active="${r.active}">${r.active ? "Hide" : "Show"}</button></td></tr>`))}</div>`;
  $("#rf").onsubmit = async (e) => {
    e.preventDefault();
    try { await api("/api/admin/rewards", "POST", { name: $("#rn").value, description: $("#rd").value, points_cost: +$("#rc").value, stock: $("#rs").value }); await Rewards(); }
    catch (err) { say($("#rmsg"), err.message, "bad"); }
  };
  view.onclick = async (e) => {
    const id = e.target.dataset?.toggle; if (!id) return;
    await api(`/api/admin/rewards/${id}`, "PUT", { active: e.target.dataset.active === "1" ? 0 : 1 }); await Rewards();
  };
}

// ------------------------------------------------------------ claims
async function Claims() {
  const rows = await api("/api/admin/claims");
  view.innerHTML = `<div class="panel"><h2>Reward claims</h2><div id="cmsg" class="msg" role="status"></div>${table(
    ["#", "Customer", "Reward", "Points", "Status", "Date", ""],
    rows.map((c) => `<tr><td>${c.id}</td><td>${esc(c.customer)}<br><span class="muted">${esc(c.email)}</span></td><td>${esc(c.reward)}</td>
    <td class="num">${c.points_spent}</td><td>${pill(c.status)}</td><td>${fmtDate(c.created_at)}</td>
    <td>${c.status === "pending" ? `<button class="small" data-s="fulfilled" data-id="${c.id}">Mark fulfilled</button>
    <button class="danger small" data-s="cancelled" data-id="${c.id}">Cancel + refund</button>` : ""}</td></tr>`))}</div>`;
  view.onclick = async (e) => {
    const { s, id } = e.target.dataset; if (!s) return;
    if (s === "cancelled" && !confirm("Cancel this claim and refund the points?")) return;
    try { await api(`/api/admin/claims/${id}/status`, "POST", { status: s }); await Claims(); } catch (err) { say($("#cmsg"), err.message, "bad"); }
  };
}

// ------------------------------------------------------------ customers
async function Customers() {
  const rows = await api("/api/admin/customers");
  view.innerHTML = `<div class="panel"><h2>Customers</h2><p class="muted">Sorted by failed code attempts in the last 7 days.</p>${table(
    ["Name", "Email", "Points", "Codes redeemed", "Failed (7d)", "Status", ""],
    rows.map((c) => `<tr><td>${esc(c.name)}</td><td>${esc(c.email)}</td><td class="num">${c.points_balance}</td><td class="num">${c.codes_redeemed}</td>
    <td class="num">${c.failures_7d}</td><td>${pill(c.status)}</td>
    <td><button class="${c.status === "active" ? "danger" : "ghost"} small" data-id="${c.id}" data-s="${c.status === "active" ? "suspended" : "active"}">${c.status === "active" ? "Suspend" : "Reinstate"}</button></td></tr>`))}</div>`;
  view.onclick = async (e) => {
    const { s, id } = e.target.dataset; if (!s) return;
    await api(`/api/admin/customers/${id}/status`, "POST", { status: s }); await Customers();
  };
}

// ------------------------------------------------------------ fraud log
async function Fraud() {
  const kind = Fraud.kind || "";
  const rows = await api("/api/admin/events" + (kind ? `?kind=${encodeURIComponent(kind)}` : ""));
  const kinds = ["", "redeem_ok", "redeem_malformed", "redeem_invalid", "redeem_used", "redeem_voided", "redeem_expired", "redeem_locked", "login_fail"];
  view.innerHTML = `<div class="panel"><h2>Security & redemption log</h2>
    <label for="fk">Filter</label><select id="fk">${kinds.map((k) => `<option value="${k}" ${k === kind ? "selected" : ""}>${k || "all events"}</option>`).join("")}</select>
    <p class="muted"><b>redeem_used</b> with a different "first_used_by" means someone is sharing or guessing codes. Repeated <b>redeem_invalid</b> from one account or IP means code-guessing. Suspend repeat offenders on the Customers tab.</p>
    ${table(["Time (UTC)", "Event", "Customer", "IP", "Detail"], rows.map((r) => `<tr><td>${fmtDate(r.created_at)}</td><td>${esc(r.kind)}</td><td>${esc(r.customer || "")}</td><td>${esc(r.ip)}</td><td>${esc(r.detail)}</td></tr>`))}</div>`;
  $("#fk").onchange = (e) => { Fraud.kind = e.target.value; Fraud(); };
}
