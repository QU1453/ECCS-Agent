/* =====================================================================
   ECCS 商城交互：货架渲染 → 下单 → 模拟支付 → 引导去问 AI 客服
   数据链路：/api/shop/products（读库）→ /api/shop/buy → /api/shop/pay
   ===================================================================== */
"use strict";

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const escapeHTML = (s) => String(s).replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ---------- 货架 ---------- */
let products = [];
let current = null;   // 当前弹层商品
let qty = 1;

async function loadProducts() {
  const res = await fetch("/api/shop/products");
  products = await res.json();
  $("#grid").innerHTML = products.map(p => `
    <div class="prod">
      <img src="${escapeHTML(p.img)}" alt="${escapeHTML(p.name)}">
      <div class="p-body">
        <div class="p-name">${escapeHTML(p.name)}</div>
        <div class="p-feature">${escapeHTML(p.feature)}</div>
        <div class="p-row">
          <span class="p-price"><small>¥</small>${p.price}</span>
          <button class="btn" data-code="${escapeHTML(p.code)}">立即购买</button>
        </div>
      </div>
    </div>`).join("");
  $$("#grid .btn").forEach(b =>
    b.addEventListener("click", () => openModal(products.find(p => p.code === b.dataset.code))));
}

/* ---------- 下单 / 支付弹层 ---------- */
function openModal(p) {
  if (!p) return;
  current = p; qty = 1;
  $("#mImg").src = p.img;
  $("#mName").textContent = p.name;
  $("#mFeature").textContent = p.feature;
  $("#mPrice").textContent = p.price;
  $("#qtyVal").textContent = qty;
  $("#buyBtn").hidden = false;
  $("#payArea").hidden = true;
  $("#doneArea").hidden = true;
  $("#modalMask").hidden = false;
}

function closeModal() { $("#modalMask").hidden = true; }

async function submitOrder() {
  if (!current) return;
  const btn = $("#buyBtn");
  btn.disabled = true; btn.textContent = "生成订单中…";
  try {
    const res = await fetch("/api/shop/buy", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ product_code: current.code, qty })
    });
    const j = await res.json();
    if (!res.ok) throw new Error(j.error || "下单失败");
    // 进入支付态
    $("#payOrderNo").textContent = j.order_no;
    $("#payTotal").textContent = j.total;
    $("#buyBtn").hidden = true;
    $("#payArea").hidden = false;
  } catch (e) {
    alert(e.message);
  } finally {
    btn.disabled = false; btn.textContent = "提交订单";
  }
}

async function payOrder() {
  const btn = $("#payBtn");
  btn.disabled = true; btn.textContent = "支付中…";
  try {
    const res = await fetch("/api/shop/pay", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ order_no: $("#payOrderNo").textContent })
    });
    const j = await res.json();
    if (!res.ok) throw new Error(j.error || "支付失败");
    $("#doneOrderNo").textContent = j.order_no;
    $("#doneNo2").textContent = j.order_no;
    $("#payArea").hidden = true;
    $("#doneArea").hidden = false;
  } catch (e) {
    alert(e.message);
    btn.disabled = false; btn.textContent = "模拟支付（演示用，不收真钱）";
  }
}

/* ---------- 我的订单查询 ---------- */
async function lookupOrder() {
  const no = $("#orderNo").value.trim();
  if (!no) return;
  const box = $("#orderBox");
  box.innerHTML = "<p style='color:#8a7f76;font-size:13px'>查询中…</p>";
  try {
    const res = await fetch("/api/shop/orders/" + encodeURIComponent(no));
    const j = await res.json();
    if (!res.ok) { box.innerHTML = `<p style='color:#c1502e;font-size:13px'>${escapeHTML(j.error || "查询失败")}</p>`; return; }
    box.innerHTML = `
      <div class="order-detail">
        <div class="o-title">订单 ${escapeHTML(j.order_no)} · ${escapeHTML(j.carrier)} · ${escapeHTML(j.paid_at || "未付款")}</div>
        <div class="o-row">
          <img src="${escapeHTML(j.product.img)}" alt="">
          <div><b>${escapeHTML(j.product.name)}</b>
            <div class="sub">¥${j.product.price} × ${j.qty} · 合计 ¥${j.total}</div>
          </div>
        </div>
        <div class="track">${j.steps.map(s => `<span class="tp ${s.state}">${escapeHTML(s.label)}</span>`).join("")}</div>
      </div>`;
  } catch {
    box.innerHTML = "<p style='color:#c1502e;font-size:13px'>网络异常，请稍后再试</p>";
  }
}

/* ---------- 事件绑定 ---------- */
$("#qtyMinus").addEventListener("click", () => { qty = Math.max(1, qty - 1); $("#qtyVal").textContent = qty; });
$("#qtyPlus").addEventListener("click", () => { qty = Math.min(9, qty + 1); $("#qtyVal").textContent = qty; });
$("#buyBtn").addEventListener("click", submitOrder);
$("#payBtn").addEventListener("click", payOrder);
$("#modalClose").addEventListener("click", closeModal);
$("#modalMask").addEventListener("click", e => { if (e.target.id === "modalMask") closeModal(); });
$("#lookupBtn").addEventListener("click", lookupOrder);
$("#orderNo").addEventListener("keydown", e => { if (e.key === "Enter") lookupOrder(); });

loadProducts();
