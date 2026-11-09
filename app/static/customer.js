import { $, api, esc, say, fmtDate } from "/static/common.js";

let mode = "login";
const REASONS = { code_redeem: "Box code", reward_claim: "Reward claimed", claim_refund: "Claim refunded" };

function setMode(m) {
  mode = m;
  $("#tab-login").setAttribute("aria-selected", m === "login");
  $("#tab-register").setAttribute("aria-selected", m === "register");
  $("#name-wrap").classList.toggle("hidden", m !== "register");
  $("#auth-submit").textContent = m === "login" ? "Log in" : "Create account";
  $("#password").autocomplete = m === "login" ? "current-password" : "new-password";
  say($("#auth-msg"), "");
}
$("#tab-login").onclick = () => setMode("login");
$("#tab-register").onclick = () => setMode("register");

$("#auth-form").onsubmit = async (e) => {
  e.preventDefault();
  const body = { email: $("#email").value, password: $("#password").value };
  if (mode === "register") body.name = $("#name").value;
  try { await api(mode === "login" ? "/api/login" : "/api/register", "POST", body); await show(); }
  catch (err) { say($("#auth-msg"), err.message, "bad"); }
};

$("#logout").onclick = async () => { await api("/api/logout", "POST", {}); location.reload(); };

// Auto-insert dashes while typing: XXXX-XXXX-XXXX-XX
$("#code").addEventListener("input", (e) => {
  const raw = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 14);
  e.target.value = raw.match(/.{1,4}/g)?.join("-") ?? "";
});

$("#redeem-form").onsubmit = async (e) => {
  e.preventDefault();
  try {
    const r = await api("/api/redeem", "POST", { code: $("#code").value });
    say($("#redeem-msg"), `+${r.points_earned} points for ${r.product}!`, "ok");
    $("#code").value = "";
    await refresh();
  } catch (err) { say($("#redeem-msg"), err.message, "bad"); }
};

async function refresh() {
  const [me, rewards, hist] = await Promise.all([api("/api/me"), api("/api/rewards"), api("/api/history")]);
  $("#hello").textContent = `Hi ${me.name}`;
  $("#balance").textContent = me.points_balance;
  $("#rewards").innerHTML = rewards.length ? rewards.map((r) => `
    <div class="reward"><b>${esc(r.name)}</b><span class="muted">${esc(r.description)}</span>
    <span class="cost">${r.points_cost} pts</span>
    <button data-id="${r.id}" ${!r.available || me.points_balance < r.points_cost ? "disabled" : ""}>
      ${!r.available ? "Out of stock" : me.points_balance < r.points_cost ? `${r.points_cost - me.points_balance} more points` : "Claim"}</button></div>`).join("")
    : '<p class="muted">No rewards available yet.</p>';
  $("#claims").innerHTML = hist.claims.map((c) => `<tr><td>${esc(c.reward)}</td><td class="num">${c.points_spent}</td>
    <td><span class="pill ${esc(c.status)}">${esc(c.status)}</span></td><td>${fmtDate(c.created_at)}</td></tr>`).join("")
    || '<tr><td colspan="4" class="muted">Nothing claimed yet.</td></tr>';
  $("#ledger").innerHTML = hist.ledger.map((l) => `<tr><td>${fmtDate(l.created_at)}</td>
    <td>${esc(REASONS[l.reason] || l.reason)}${l.note ? ` · ${esc(l.note)}` : ""}</td>
    <td class="num">${l.delta > 0 ? "+" : ""}${l.delta}</td></tr>`).join("")
    || '<tr><td colspan="3" class="muted">No activity yet.</td></tr>';
}

$("#rewards").onclick = async (e) => {
  const id = e.target.dataset?.id;
  if (!id) return;
  try { await api(`/api/rewards/${id}/claim`, "POST", {}); say($("#reward-msg"), "Claimed! The factory will arrange delivery.", "ok"); await refresh(); }
  catch (err) { say($("#reward-msg"), err.message, "bad"); }
};

async function show() {
  $("#auth").classList.add("hidden"); $("#app").classList.remove("hidden"); $("#logout").classList.remove("hidden");
  await refresh();
}
api("/api/me").then(show).catch(() => {});
