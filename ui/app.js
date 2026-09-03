/* =====================================================================
   ECCS 智能客服 · 单对话窗口交互
   演示版：关键词路由模拟 Agent，真实版替换 answer() 为 Python 后端调用
   ===================================================================== */
"use strict";

const $ = (s, r = document) => r.querySelector(s);
const IMG = p => "https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=" + p + "&image_size=square";
const now = () => { const d = new Date(); return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; };

/* ---------- 商品演示数据 ---------- */
const PRODUCTS = {
  earbuds:  { name: "云感无线蓝牙耳机 Pro · 半入耳", price: 299, img: IMG("studio%20product%20photo%20minimalist%20white%20wireless%20earbuds%20open%20charging%20case%20soft%20warm%20beige%20background") },
  keyboard: { name: "奶糖机械键盘 87 键 · 奶油橙",   price: 459, img: IMG("studio%20product%20photo%20retro%20cream%20mechanical%20keyboard%20warm%20orange%20keycaps%20soft%20beige%20background") },
  tumbler:  { name: "山雾保温杯 450ml · 燕麦奶",      price: 129, img: IMG("studio%20product%20photo%20cream%20matte%20insulated%20tumbler%20with%20lid%20warm%20beige%20background") },
  power:    { name: "珊瑚移动电源 10000mAh · 快充",   price: 189, img: IMG("studio%20product%20photo%20slim%20coral%20orange%20power%20bank%20warm%20neutral%20background") }
};

const msgs = $("#msgs");
const scrollBottom = () => msgs.scrollTop = msgs.scrollHeight;

/* ---------- 气泡渲染 ---------- */
function addMsg(who, html, cardHTML) {
  const div = document.createElement("div");
  div.className = `msg ${who}`;
  div.innerHTML = `
    <div class="avatar">E</div>
    <div style="min-width:0">
      <div class="bubble">${html}${cardHTML ? `<div class="card">${cardHTML}</div>` : ""}</div>
      <div class="time">${now()}</div>
    </div>`;
  msgs.appendChild(div);
  scrollBottom();
  return div;
}
function showTyping() {
  const div = document.createElement("div");
  div.className = "msg ai typing";
  div.innerHTML = `<div class="avatar">E</div><div style="min-width:0"><div class="bubble"><i></i><i></i><i></i></div></div>`;
  msgs.appendChild(div); scrollBottom();
  return div;
}

/* 演示订单（离线兜底渲染用，与后端 tools.py 数据一致） */
const ORDER_DEMO = {
  order_no: "2026081200012",
  carrier: "顺丰速运",
  paid_at: "昨天 15:02 付款",
  qty: 1,
  total: 299,
  product: PRODUCTS.earbuds,
  steps: [
    { label: "已付款", state: "done" },
    { label: "运输中", state: "cur" },
    { label: "派送中", state: "" },
    { label: "已签收", state: "" }
  ]
};

/* 订单卡片 / 商品卡片（orderCard 兼容后端返回的 order 数据结构） */
const orderCard = (o = ORDER_DEMO) => `
  <div class="card-title"><svg viewBox="0 0 24 24"><path d="M3 7h11v8H3zM14 10h4l3 3v2h-7z"/><circle cx="7" cy="17.4" r="1.6"/><circle cx="17.4" cy="17.4" r="1.6"/></svg>订单 ${o.order_no} · ${o.carrier}</div>
  <div class="order-row">
    <img src="${o.product.img}" alt="商品">
    <div><b>${o.product.name}</b><div class="sub">¥${o.product.price} × ${o.qty} · ${o.paid_at}</div></div>
  </div>
  <div class="track">
    ${o.steps.map(s => `<span class="tp ${s.state}">${s.label}</span>`).join("")}
  </div>`;

const recoCard = (items) => `
  <div class="card-title"><svg viewBox="0 0 24 24"><path d="m12 3 2.6 5.3L20 9l-4 3.8.9 5.6L12 15.9 7.1 18.4 8 12.8 4 9l5.4-.7z"/></svg>智能推荐 · 商品库命中</div>
  <div class="link-row">${items.map(p => `
    <div class="prod-card"><img src="${p.img}" alt="${p.name}"><b>${p.name}</b><div class="price"><small>¥</small>${p.price}</div></div>`).join("")}
  </div>`;

/* ---------- 模拟 Agent 回复（真实版替换为后端调用） ---------- */
const DELAY = () => 900 + Math.random() * 700;

function answer(q) {
  const s = q.toLowerCase();
  if (/物流|快递|到哪|发货|订单|单号|签收/.test(s))
    return { html: "您的订单当前处于 <span class='em'>「运输中 · 广州转运中心」</span>，预计明天 18:00 前送达，到达派送点会有短信提醒～", card: orderCard() };
  if (/退|换|退款|售后|质量|坏了/.test(s))
    return { html: "可以的～该订单在 <span class='em'>7 天无理由</span> 期限内，已为您登记售后单 <span class='em'>#SA-2033</span>。<br>① 仅退款（原路退回 ¥299）　② 换新（免运费优先发）　③ 退货退款" };
  if (/推荐|耳机|键盘|保温杯|充电宝|什么好|哪款/.test(s))
    return { html: "根据您的需求推荐这 3 款高口碑好物，最推荐第一款，支持主动降噪、佩戴很舒适：", card: recoCard([PRODUCTS.earbuds, PRODUCTS.keyboard, PRODUCTS.power]) };
  if (/在吗|你好|哈喽|hi|hello/.test(s))
    return { html: "您好呀～我是 ECCS 的 AI 智能客服，可以帮您查物流、办退换、挑商品，请直接告诉我需求即可～" };
  return { html: "收到～这个问题我可以处理。<br>您可以试试问我：<span class='em'>订单到哪了 / 怎么退货 / 推荐一款耳机</span>。" };
}

/* ---------- 发送流程 ---------- */
const input = $("#input");
let busy = false;

async function send() {
  const q = input.value.trim();
  if (!q || busy) return;
  busy = true;
  input.value = ""; autoGrow(input);

  addMsg("user", escapeHTML(q));
  const typing = showTyping();
  $("#hint").textContent = "智能体思考中…";

  const local = answer(q);
  const res = await window.askAgent(q);   // 真实版：POST /api/ask → Python Agent
  const a = (res && res.reply) ? res : { reply: local.html, card: local.card }; // 后端不可达时回退本地演示

  await wait(DELAY());
  typing.remove();
  const card = a.card || cardFrom(a.intent, a.data); // 卡片：离线直给 / 后端结构化渲染
  addMsg("ai", a.reply, card);
  $("#hint").textContent = (a.data || a.card) ? "智能体已回复（带卡片）" : "AI 智能体自动接待 · 平均耗时 1.5s";
  busy = false;
}

/* 把后端返回的 intent/data 渲染成卡片 HTML；无匹配返回空串 */
function cardFrom(intent, data) {
  if (!data) return "";
  if (intent === "order") return orderCard(data);
  if (intent === "recommend" && Array.isArray(data.items)) return recoCard(data.items);
  return "";
}

/* 后端桥接：窗口输入 → Python Agent（FastAPI /api/ask），失败自动回退本地演示 */
if (!window.askAgent) window.askAgent = async q => {
  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: q, session_id: "demo" })
    });
    if (!res.ok) throw new Error("backend not ok");
    const j = await res.json();
    if (j && j.reply) return { reply: j.reply, intent: j.intent || "none", data: j.data || null };
    throw new Error("empty reply");
  } catch (e) {
    const l = answer(q); // 纯静态预览（无后端）仍可演示
    return { reply: l.html, card: l.card };
  }
};

function escapeHTML(s) {
  return s.replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const wait = ms => new Promise(r => setTimeout(r, ms));
const autoGrow = t => { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 120) + "px"; };

/* ---------- 事件 ---------- */
$("#sendBtn").addEventListener("click", send);
input.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
input.addEventListener("input", () => autoGrow(input));
$$(".quick").forEach(b => b.addEventListener("click", () => { input.value = b.dataset.q; autoGrow(input); send(); }));
$("#clearBtn").addEventListener("click", () => {
  msgs.innerHTML = "";
  addMsg("ai", "已清空对话。需要帮忙查物流、办退换或挑商品吗？");
});

/* ---------- 启动问候 ---------- */
addMsg("ai", "您好呀～我是 <b>ECCS 智能客服</b>，24 小时在线。<br>可以帮您 <span class='em'>查物流</span>、<span class='em'>办退换</span>、<span class='em'>挑商品</span>，请问需要什么帮助？");

/* 小工具查询 */
function $$(s) { return [...document.querySelectorAll(s)]; }
