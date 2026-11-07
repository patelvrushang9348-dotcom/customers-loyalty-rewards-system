/* Openbox Rewards front end: vanilla JS, hash router, no build step. */
const $app = document.getElementById('app');
const $top = document.getElementById('top');
let me = null;
let lastBatch = null; // plain codes of the newest batch, kept in memory only

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = s => s ? new Date(s.replace(' ', 'T') + 'Z').toLocaleString([], {dateStyle: 'medium', timeStyle: 'short'}) : '';
const num = n => Number(n).toLocaleString();

async function api(path, {method = 'GET', body} = {}) {
  const res = await fetch('/api' + path, {
    method, credentials: 'same-origin',
    headers: {'Content-Type': 'application/json', 'X-Requested-With': 'fetch'},
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = {};
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) { const e = new Error(data.error || 'Something went wrong. Try again.'); e.status = res.status; throw e; }
  return data;
}

let toastTimer;
function toast(text) {
  const t = document.getElementById('toast');
  t.textContent = text; t.classList.add('show');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove('show'), 3200);
}

function table(heads, rows, empty) {
  if (!rows.length) return `<div class="empty">${esc(empty)}</div>`;
  return `<div class="table-wrap"><table><thead><tr>${heads.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>` +
    rows.map(r => `<tr>${r.map((c, i) => `<td data-label="${esc(heads[i])}"><div class="cell">${c}</div></td>`).join('')}</tr>`).join('') + `</tbody></table></div>`;
}
const statusTag = s => ({unused: 'ok', redeemed: 'warn', voided: 'bad', active: 'ok', pending: 'warn', fulfilled: 'ok', rejected: 'bad'}[s] || '');
const tag = s => `<span class="tag ${statusTag(s)}">${esc(s)}</span>`;

/* ---------- chrome ---------- */
const CUSTOMER_NAV = [['/', 'Redeem'], ['/rewards', 'Rewards'], ['/account', 'My points']];
const ADMIN_NAV = [['/admin', 'Overview'], ['/admin/batches', 'Batches'], ['/admin/rewards', 'Rewards'], ['/admin/claims', 'Claims'], ['/admin/customers', 'Customers'], ['/admin/alerts', 'Fraud alerts']];

function renderTop(path) {
  const links = me && me.role === 'admin' ? ADMIN_NAV : CUSTOMER_NAV;
  $top.innerHTML = `<div class="top-in"><a class="brand" href="#/"><i></i>Openbox</a>
    <nav class="nav" aria-label="Main">${links.map(([p, l]) => `<a href="#${p}" ${p === path ? 'aria-current="page"' : ''}>${l}</a>`).join('')}</nav>
    <div class="who">${me
      ? `${me.role === 'customer' ? `<span class="pts" title="Your points">${num(me.points)} pts</span>` : '<span class="small">Factory owner</span>'}<button class="btn ghost" id="logout">Sign out</button>`
      : `<a class="btn ghost" href="#/login">Sign in</a>`}</div></div>`;
  const lo = document.getElementById('logout');
  if (lo) lo.onclick = async () => { await api('/logout', {method: 'POST'}); me = null; go('/'); };
}

function go(path) { location.hash = '#' + path; if (location.hash === '#' + path) route(); }

/* ---------- customer pages ---------- */
function flapCard() {
  return `<section class="flap" aria-labelledby="fh"><h2 id="fh">Found a code inside your box?</h2>
    <form id="redeem" novalidate><label for="code">Box code</label>
    <input id="code" class="code-input" inputmode="text" autocomplete="off" autocapitalize="characters" spellcheck="false" maxlength="14" placeholder="XXXX-XXXX-XXXX">
    <button class="btn" type="submit">${me ? 'Claim points' : 'Sign in to claim points'}</button></form>
    <div class="msg" id="msg" aria-live="polite"></div>
    <div class="perf"></div><p class="small muted" style="margin:0">Printed on the inside flap. Each code works once, for one account.</p></section>`;
}

function bindRedeem() {
  const input = document.getElementById('code'), msg = document.getElementById('msg');
  input.addEventListener('input', () => {
    const raw = input.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 12);
    input.value = raw.match(/.{1,4}/g)?.join('-') || '';
  });
  document.getElementById('redeem').addEventListener('submit', async e => {
    e.preventDefault();
    if (!me) return go('/login');
    const btn = e.target.querySelector('button'); btn.disabled = true; msg.className = 'msg'; msg.textContent = 'Checking code…';
    try {
      const r = await api('/codes/redeem', {method: 'POST', body: {code: input.value}});
      me = r.user; renderTop('/');
      document.querySelector('.flap').innerHTML = `<div class="stamp"><div class="stamp-mark">+${num(r.points_added)}</div>
        <h2 style="margin-top:1rem">Points added</h2><p class="muted">${esc(r.product)} · you now have ${num(me.points)} points.</p>
        <div class="row" style="width:100%"><a class="btn" href="#/rewards">See rewards</a><button class="btn ghost" id="again">Enter another code</button></div></div>`;
      document.getElementById('again').onclick = route;
    } catch (err) {
      msg.className = 'msg err'; msg.textContent = err.message; btn.disabled = false;
    }
  });
}

function pageHome() {
  if (me && me.role === 'admin') return go('/admin');
  $app.innerHTML = `<div class="hero"><div>
      <h1>Every box you open is worth points.</h1>
      <p class="lead">Buy our products, enter the code printed inside the box, and collect points toward free products and gifts from the factory.</p>
      ${me ? '' : '<a class="btn dark" href="#/register">Create a free account</a>'}</div>${flapCard()}</div>
    <section class="section"><h2>How it works</h2><ol class="how">
      <li><h3>Open the box</h3><p class="muted">Find the 12-character code on the inside flap.</p></li>
      <li><h3>Enter the code</h3><p class="muted">Sign in, type the code and the points land in your account at once.</p></li>
      <li><h3>Pick a reward</h3><p class="muted">Trade points for gifts. The more you buy, the higher your tier.</p></li></ol></section>`;
  bindRedeem();
}

async function pageRewards() {
  $app.innerHTML = '<h1>Rewards</h1><p class="muted">Loading…</p>';
  const {items} = await api('/rewards');
  const pts = me ? me.points : 0;
  $app.innerHTML = `<h1>Rewards</h1><p class="lead muted">${me ? `You have <b>${num(pts)}</b> points.` : 'Sign in to see your points and claim rewards.'}</p>` +
    (items.length ? `<div class="grid three">${items.map(r => {
      const out = r.stock < 1, can = me && pts >= r.cost && !out;
      return `<article class="reward"><div class="band"><h3 style="margin:0">${esc(r.name)}</h3><b>${num(r.cost)}</b></div>
        <div class="body"><p class="muted">${esc(r.description)}</p>
        <div style="display:flex;justify-content:space-between;align-items:center;gap:.5rem">
        ${out ? '<span class="tag bad">Out of stock</span>' : r.stock <= 5 ? `<span class="tag warn">${r.stock} left</span>` : '<span class="tag ok">In stock</span>'}
        <button class="btn sm ${can ? '' : 'ghost'}" data-claim="${r.id}" data-cost="${r.cost}" ${out ? 'disabled' : ''}>${!me ? 'Sign in' : can ? 'Claim' : `Need ${num(r.cost - pts)} more`}</button></div></div></article>`;
    }).join('')}</div>` : '<div class="empty">No rewards are available right now. Check back soon.</div>');
  $app.querySelectorAll('[data-claim]').forEach(b => b.onclick = async () => {
    if (!me) return go('/login');
    if (me.points < +b.dataset.cost) return toast('Not enough points yet. Keep opening boxes!');
    if (!confirm('Spend ' + b.dataset.cost + ' points on this reward?')) return;
    try { const r = await api(`/rewards/${b.dataset.claim}/claim`, {method: 'POST'}); me = r.user; toast('Reward claimed. The factory will contact you.'); route(); }
    catch (e) { toast(e.message); }
  });
}

async function pageAccount() {
  const [{items: hist}, {items: claims}, {user}] = await Promise.all([api('/history'), api('/claims'), api('/me')]);
  me = user; const t = me.tier;
  const pct = t.ceiling ? Math.min(100, Math.round(100 * (me.lifetime - t.floor) / (t.ceiling - t.floor))) : 100;
  $app.innerHTML = `<h1>My points</h1>
    <div class="balance"><div><div class="small">Available points</div><div class="big">${num(me.points)}</div></div>
      <div class="tier"><b>${esc(t.name)} member</b> · ${num(me.lifetime)} earned in total
        <div class="bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"><span style="width:${pct}%"></span></div>
        <div class="small">${t.next ? `${num(t.to_next)} points to ${esc(t.next)}` : 'Top tier reached. Thank you!'}</div></div></div>
    <div class="grid two section"><div><h2>Activity</h2>${table(['When', 'What', 'Points'], hist.map(h => [fmt(h.created_at), esc(h.reason), `<b style="color:${h.delta > 0 ? 'var(--moss)' : 'var(--stamp)'}">${h.delta > 0 ? '+' : ''}${num(h.delta)}</b>`]), 'No activity yet. Enter your first box code.')}</div>
    <div><h2>Claimed rewards</h2>${table(['Reward', 'Status', 'Points'], claims.map(c => [esc(c.name), tag(c.status), num(c.cost)]), 'You have not claimed a reward yet.')}</div></div>`;
  renderTop('/account');
}

function pageAuth(mode) {
  const reg = mode === 'register';
  $app.innerHTML = `<div class="auth panel"><h1 style="font-size:2rem">${reg ? 'Create your account' : 'Sign in'}</h1>
    <form id="auth" novalidate>${reg ? '<div class="field"><label for="name">Name</label><input id="name" autocomplete="name" required></div>' : ''}
    <div class="field"><label for="email">Email</label><input id="email" type="email" autocomplete="email" required></div>
    <div class="field"><label for="pw">Password${reg ? ' (8+ characters)' : ''}</label><input id="pw" type="password" autocomplete="${reg ? 'new-password' : 'current-password'}" required></div>
    <button class="btn" style="width:100%">${reg ? 'Create account' : 'Sign in'}</button><div class="msg err" id="msg"></div></form>
    <p class="small muted" style="margin:1rem 0 0">${reg ? 'Already have an account? <a href="#/login">Sign in</a>' : 'New here? <a href="#/register">Create an account</a>'}</p></div>`;
  document.getElementById('auth').onsubmit = async e => {
    e.preventDefault();
    const val = id => document.getElementById(id).value;
    const body = {email: val('email'), password: val('pw')}; if (reg) body.name = val('name');
    try { me = (await api(reg ? '/register' : '/login', {method: 'POST', body})).user; go(me.role === 'admin' ? '/admin' : '/'); }
    catch (err) { document.getElementById('msg').textContent = err.message; }
  };
}

/* ---------- admin pages ---------- */
function barChart(days) {
  const max = Math.max(1, ...days.map(d => d.count)), W = 560, H = 150, bw = W / days.length;
  return `<svg class="chart" viewBox="0 0 ${W} ${H + 24}" role="img" aria-label="Boxes redeemed per day, last 14 days">` +
    days.map((d, i) => {
      const h = Math.round((d.count / max) * H);
      return `<rect x="${i * bw + 4}" y="${H - h}" width="${bw - 8}" height="${Math.max(h, 2)}" rx="2"><title>${d.day}: ${d.count}</title></rect>`;
    }).join('') + `<text x="0" y="${H + 18}">${days[0].day.slice(5)}</text><text x="${W}" y="${H + 18}" text-anchor="end">${days.at(-1).day.slice(5)}</text><text x="0" y="10">peak ${max}</text></svg>`;
}

async function adminOverview() {
  const s = await api('/admin/stats');
  const k = (v, l, hot) => `<div class="kpi ${hot ? 'hot' : ''}"><b>${v}</b><span>${l}</span></div>`;
  $app.innerHTML = `<h1 style="font-size:2.4rem">Overview</h1>
    <div class="kpis">${k(num(s.customers), 'Customers')}${k(num(s.codes_redeemed) + '/' + num(s.codes_total), 'Codes redeemed')}${k(s.redeem_rate + '%', 'Redeem rate')}
    ${k(num(s.points_issued), 'Points issued')}${k(num(s.pending_claims), 'Claims to fulfil', s.pending_claims > 0)}${k(num(s.failed_24h), 'Failed codes, 24h', s.failed_24h > 10)}</div>
    <div class="grid two section"><div class="panel"><h2>Boxes redeemed, last 14 days</h2>${barChart(s.daily)}</div>
    <div class="panel"><h2>Top products</h2>${table(['Product', 'Boxes'], s.top_products.map(p => [esc(p.name), num(p.n)]), 'No boxes redeemed yet.')}
    <p class="small muted">Points spent on rewards: ${num(s.points_spent)}</p></div></div>`;
}

function downloadCsv(batch) {
  const csv = 'serial,code\n' + batch.codes.map(c => `${c.serial},${c.code}`).join('\n') + '\n';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], {type: 'text/csv'})); a.download = `batch-${batch.batch_id}-codes.csv`; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

async function adminBatches() {
  const [{items: prods}, {items: batches}] = await Promise.all([api('/admin/products'), api('/admin/batches')]);
  const live = lastBatch ? `<div class="notice"><b>Batch ${lastBatch.batch_id} created: ${num(lastBatch.codes.length)} codes for ${esc(lastBatch.product)}.</b>
    <p class="small" style="margin:.4rem 0 .8rem">Download the file now and send it to your printer. For security the codes are not stored, so they cannot be shown again.</p>
    <button class="btn dark" id="dl">Download codes (CSV)</button></div>` : '';
  $app.innerHTML = `<h1 style="font-size:2.4rem">Batches</h1>${live}
    <div class="grid two"><form class="panel" id="bf"><h2>Generate codes</h2>
      <div class="field"><label for="bp">Product</label><select id="bp">${prods.map(p => `<option value="${p.id}">${esc(p.name)} (${p.points} pts)</option>`).join('')}</select></div>
      <div class="row"><div class="field"><label for="bq">Number of boxes</label><input id="bq" type="number" min="1" max="5000" value="100"></div>
      <div class="field"><label for="bn">Note (optional)</label><input id="bn" maxlength="200" placeholder="e.g. Line 2, 7 Nov"></div></div>
      <button class="btn">Generate codes</button><div class="msg err" id="bm"></div></form>
    <form class="panel" id="pf"><h2>Add a product</h2>
      <div class="row"><div class="field"><label for="ps">SKU</label><input id="ps" maxlength="8" placeholder="CHOC"></div>
      <div class="field"><label for="pp">Points per box</label><input id="pp" type="number" min="1" value="50"></div></div>
      <div class="field"><label for="pn">Product name</label><input id="pn"></div>
      <button class="btn ghost">Add product</button><div class="msg err" id="pm"></div></form></div>
    <div class="section"><h2>All batches</h2>${table(['#', 'Product', 'Created', 'Size', 'Redeemed', 'Status', ''],
      batches.map(b => [b.id, esc(b.product) + (b.note ? `<br><span class="small muted">${esc(b.note)}</span>` : ''), fmt(b.created_at), num(b.quantity), num(b.redeemed), tag(b.status),
        b.status === 'active' ? `<button class="btn danger sm" data-void="${b.id}">Cancel unused codes</button>` : '']), 'No batches yet. Generate your first one above.')}</div>
    <div class="section"><h2>Look up a code by serial</h2><div class="row"><input id="q" placeholder="e.g. CHOC-0001" aria-label="Serial number"><button class="btn ghost" id="qb" style="flex:0 0 auto">Search</button></div><div id="qr" style="margin-top:1rem"></div></div>`;
  if (lastBatch) document.getElementById('dl').onclick = () => downloadCsv(lastBatch);
  document.getElementById('bf').onsubmit = async e => {
    e.preventDefault();
    try { lastBatch = await api('/admin/batches', {method: 'POST', body: {product_id: +bp.value, quantity: +bq.value, note: bn.value}}); toast('Batch created'); adminBatches(); }
    catch (err) { bm.textContent = err.message; }
  };
  document.getElementById('pf').onsubmit = async e => {
    e.preventDefault();
    try { await api('/admin/products', {method: 'POST', body: {sku: ps.value, name: pn.value, points: +pp.value}}); toast('Product added'); adminBatches(); }
    catch (err) { pm.textContent = err.message; }
  };
  $app.querySelectorAll('[data-void]').forEach(b => b.onclick = async () => {
    if (!confirm('Cancel every unused code in this batch? Customers will no longer be able to redeem them.')) return;
    try { const r = await api(`/admin/batches/${b.dataset.void}/void`, {method: 'POST'}); toast(`${r.cancelled} codes cancelled`); adminBatches(); } catch (e) { toast(e.message); }
  });
  const search = async () => {
    const {items} = await api('/admin/codes?q=' + encodeURIComponent(q.value));
    qr.innerHTML = table(['Serial', 'Status', 'Redeemed by', 'When'], items.map(c => [esc(c.serial), tag(c.status), esc(c.redeemed_by || ''), fmt(c.redeemed_at)]), 'No serial matches that search.');
  };
  document.getElementById('qb').onclick = search; q.onkeydown = e => { if (e.key === 'Enter') search(); };
}

async function adminRewards() {
  const {items} = await api('/admin/rewards');
  $app.innerHTML = `<h1 style="font-size:2.4rem">Rewards</h1>
    <form class="panel" id="rf"><h2>Add a reward</h2><div class="row">
      <div class="field"><label for="rn">Name</label><input id="rn" required></div>
      <div class="field"><label for="rc">Cost (points)</label><input id="rc" type="number" min="1" value="500"></div>
      <div class="field"><label for="rs">Stock</label><input id="rs" type="number" min="0" value="10"></div></div>
      <div class="field"><label for="rd">Description</label><input id="rd" maxlength="300"></div>
      <button class="btn">Add reward</button><div class="msg err" id="rm"></div></form>
    <div class="section">${table(['Reward', 'Cost', 'Stock', 'Visible', ''], items.map(r => [
      `<b>${esc(r.name)}</b><br><span class="small muted">${esc(r.description)}</span>`,
      `<input type="number" min="1" value="${r.cost}" data-f="cost" data-id="${r.id}" aria-label="Cost">`,
      `<input type="number" min="0" value="${r.stock}" data-f="stock" data-id="${r.id}" aria-label="Stock">`,
      `<input type="checkbox" style="width:auto;min-height:0" data-f="active" data-id="${r.id}" ${r.active ? 'checked' : ''} aria-label="Visible to customers">`,
      `<button class="btn sm" data-save="${r.id}">Save</button>`]), 'No rewards yet. Add one above so customers have something to work toward.')}</div>`;
  document.getElementById('rf').onsubmit = async e => {
    e.preventDefault();
    try { await api('/admin/rewards', {method: 'POST', body: {name: rn.value, cost: +rc.value, stock: +rs.value, description: rd.value}}); toast('Reward added'); adminRewards(); }
    catch (err) { rm.textContent = err.message; }
  };
  $app.querySelectorAll('[data-save]').forEach(b => b.onclick = async () => {
    const id = b.dataset.save, f = n => $app.querySelector(`[data-f=${n}][data-id="${id}"]`);
    try { await api('/admin/rewards/' + id, {method: 'PUT', body: {cost: +f('cost').value, stock: +f('stock').value, active: f('active').checked}}); toast('Saved'); } catch (e) { toast(e.message); }
  });
}

async function adminClaims() {
  const {items} = await api('/admin/claims');
  $app.innerHTML = `<h1 style="font-size:2.4rem">Claims</h1><p class="muted">Fulfil a claim once the reward is sent. Rejecting refunds the points and returns the item to stock.</p>` +
    table(['When', 'Customer', 'Reward', 'Points', 'Status', ''], items.map(c => [fmt(c.created_at), `${esc(c.customer)}<br><span class="small muted">${esc(c.email)}</span>`, esc(c.reward), num(c.cost), tag(c.status),
      c.status === 'pending' ? `<div class="acts"><button class="btn sm" data-c="${c.id}" data-s="fulfilled">Mark fulfilled</button><button class="btn danger sm" data-c="${c.id}" data-s="rejected">Reject</button></div>` : '']), 'No claims yet.');
  $app.querySelectorAll('[data-c]').forEach(b => b.onclick = async () => {
    if (b.dataset.s === 'rejected' && !confirm('Reject this claim and refund the points?')) return;
    try { await api('/admin/claims/' + b.dataset.c, {method: 'POST', body: {status: b.dataset.s}}); toast('Claim ' + b.dataset.s); adminClaims(); } catch (e) { toast(e.message); }
  });
}

async function adminCustomers() {
  const {items} = await api('/admin/customers');
  $app.innerHTML = `<h1 style="font-size:2.4rem">Customers</h1>` + table(['Customer', 'Boxes', 'Points', 'Earned', 'Failed codes', 'Joined', ''],
    items.map(c => [`${esc(c.name)}${c.blocked ? ' ' + tag('blocked').replace('tag ', 'tag bad ') : ''}<br><span class="small muted">${esc(c.email)}</span>`, c.boxes, num(c.points_balance), num(c.lifetime_points), c.fails, fmt(c.created_at),
      `<button class="btn sm ${c.blocked ? '' : 'danger'}" data-b="${c.id}" data-v="${c.blocked ? 0 : 1}">${c.blocked ? 'Unblock' : 'Block'}</button>`]), 'No customers have registered yet.');
  $app.querySelectorAll('[data-b]').forEach(b => b.onclick = async () => {
    if (b.dataset.v === '1' && !confirm('Block this customer? They will be signed out and unable to sign in.')) return;
    try { await api(`/admin/customers/${b.dataset.b}/block`, {method: 'POST', body: {blocked: b.dataset.v === '1'}}); adminCustomers(); } catch (e) { toast(e.message); }
  });
}

async function adminAlerts() {
  const a = await api('/admin/alerts');
  $app.innerHTML = `<h1 style="font-size:2.4rem">Fraud alerts</h1><p class="muted">Based on the last 24 hours of code attempts.</p>
    <h2>Accounts with repeated wrong codes</h2>${table(['Customer', 'Failed tries', 'Last try', ''], a.users.map(u => [esc(u.email), `<b>${u.n}</b>`, fmt(u.last), u.blocked ? tag('blocked').replace('tag ', 'tag bad ') : `<button class="btn danger sm" data-b="${u.id}">Block</button>`]), 'No suspicious accounts.')}
    <div class="section"><h2>Networks with many failures</h2>${table(['IP address', 'Failed tries', 'Accounts used'], a.ips.map(i => [esc(i.ip), `<b>${i.n}</b>`, i.accounts]), 'No suspicious networks.')}</div>
    <div class="section"><h2>Codes people keep re-submitting</h2>${table(['Serial', 'Tries', 'Accounts'], a.shared_codes.map(c => [esc(c.serial), c.tries, c.accounts]), 'No codes are being shared or reused.')}</div>
    <div class="section"><h2>Recent admin activity</h2>${table(['When', 'Who', 'Action', 'Detail'], a.audit.map(x => [fmt(x.created_at), esc(x.actor || 'system'), esc(x.action), esc(x.detail)]), 'No activity logged yet.')}</div>`;
  $app.querySelectorAll('[data-b]').forEach(b => b.onclick = async () => {
    if (!confirm('Block this customer?')) return;
    try { await api(`/admin/customers/${b.dataset.b}/block`, {method: 'POST', body: {blocked: true}}); adminAlerts(); } catch (e) { toast(e.message); }
  });
}

/* ---------- router ---------- */
const ROUTES = {
  '/': {fn: pageHome}, '/rewards': {fn: pageRewards}, '/account': {fn: pageAccount, auth: 1},
  '/login': {fn: () => pageAuth('login')}, '/register': {fn: () => pageAuth('register')},
  '/admin': {fn: adminOverview, admin: 1}, '/admin/batches': {fn: adminBatches, admin: 1}, '/admin/rewards': {fn: adminRewards, admin: 1},
  '/admin/claims': {fn: adminClaims, admin: 1}, '/admin/customers': {fn: adminCustomers, admin: 1}, '/admin/alerts': {fn: adminAlerts, admin: 1},
};

async function route() {
  const path = (location.hash.slice(1) || '/').split('?')[0];
  const r = ROUTES[path] || ROUTES['/'];
  if ((r.auth || r.admin) && !me) return go('/login');
  if (r.admin && me.role !== 'admin') return go('/');
  if (path.startsWith('/account') && me.role === 'admin') return go('/admin');
  renderTop(path);
  try { await r.fn(); } catch (e) {
    if (e.status === 401) { me = null; return go('/login'); }
    $app.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
  document.title = (path === '/' ? '' : path.split('/').pop().replace(/^./, c => c.toUpperCase()) + ' · ') + 'Openbox Rewards';
}

window.addEventListener('hashchange', () => { route(); window.scrollTo(0, 0); });
(async () => { try { me = (await api('/me')).user; } catch (_) {} route(); })();
