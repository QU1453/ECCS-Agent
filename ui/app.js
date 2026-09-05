/* =====================================================================
   ECCS 智能客服 · 单对话窗口（中/日双语）
   和纸暖帘界面：一键切换中文 ⇄ 日本語（含客服话术与卡片）
   后端桥接：POST /api/ask → Python Agent；不可达时自动回退本地演示
   ===================================================================== */
"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const IMG = p => "https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=" + p + "&image_size=square";
const now = () => { const d = new Date(); return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; };
const wait = ms => new Promise(r => setTimeout(r, ms));
const DELAY = () => 800 + Math.random() * 600;

/* ---------- 商品演示数据（中/日双语） ---------- */
const PRODUCTS = {
  earbuds:  { zh: "云感无线蓝牙耳机 Pro · 半入耳",   ja: "雲感ワイヤレスイヤホン Pro · 半インナー",        price: 299, img: IMG("studio%20product%20photo%20minimalist%20white%20wireless%20earbuds%20open%20charging%20case%20soft%20warm%20beige%20background") },
  keyboard: { zh: "奶糖机械键盘 87 键 · 奶油橙",     ja: "キャンディメカニカルキーボード 87キー · クリームオレンジ", price: 459, img: IMG("studio%20product%20photo%20retro%20cream%20mechanical%20keyboard%20warm%20orange%20keycaps%20soft%20beige%20background") },
  tumbler:  { zh: "山雾保温杯 450ml · 燕麦奶",       ja: "山霧マグボトル 450ml · オートミルク",            price: 129, img: IMG("studio%20product%20photo%20cream%20matte%20insulated%20tumbler%20with%20lid%20warm%20beige%20background") },
  power:    { zh: "珊瑚移动电源 10000mAh · 快充",    ja: "サンゴモバイルバッテリー 10000mAh · 急速充電",    price: 189, img: IMG("studio%20product%20photo%20slim%20coral%20orange%20power%20bank%20warm%20neutral%20background") }
};
/* 后端返回的中文商品名 → 日文（后端卡片数据本地化用） */
const NAME_ZH2JA = Object.fromEntries(Object.values(PRODUCTS).map(p => [p.zh, p.ja]));

/* ---------- 多语言文案 ---------- */
const I18N = {
  zh: {
    docTitle: "ECCS 智能客服", title: "ECCS 智能客服", status: "在线 · 秒回",
    placeholder: "请输入您的问题…（Enter 发送）", hint: "AI 智能体自动接待 · 平均耗时 1.5s",
    thinking: "智能体思考中…", replied: "智能体已回复", clearTip: "清空对话",
    q1: "订单到哪了？", q2: "怎么退货？", q3: "推荐一款耳机",
    greet: "您好呀～我是 <b>ECCS 智能客服</b>，24 小时在线。<br>可以帮您 <span class='em'>查物流</span>、<span class='em'>办退换</span>、<span class='em'>挑商品</span>，请问需要什么帮助？",
    switched: "已切换为中文。有什么可以帮您？",
    cleared: "已清空对话。需要帮忙查物流、办退换或挑商品吗？",
    card: { order: "订单", carrier: "顺丰速运", reco: "智能推荐 · 商品库命中", steps: ["已付款", "运输中", "派送中", "已签收"], paidAt: "昨天 15:02 付款" },
    reply: {
      logistics: "您的订单当前处于 <span class='em'>「广州转运中心」</span>，预计明天 18:00 前送达，到达派送点会有短信提醒～",
      returns: "可以的～该订单在 <span class='em'>7 天无理由</span> 期限内，已为您登记售后单 <span class='em'>#SA-2035</span>。<br>① 仅退款（原路退回）　② 换新（免运费优先发）　③ 退货退款",
      reco: "根据您的需求推荐这 3 款高口碑好物，最推荐第一款，支持主动降噪、佩戴很舒适：",
      greet: "您好呀～我是 ECCS 的 AI 智能客服，可以帮您查物流、办退换、挑商品，请直接告诉我需求即可～",
      fallback: "收到～这个问题我可以处理。<br>您可以试试问我：<span class='em'>订单到哪了 / 怎么退货 / 推荐一款耳机</span>。"
    },
    re: { logistics: /物流|快递|到哪|发货|订单|单号|签收|运输/, returns: /退|换|退款|售后|质量|坏了/, reco: /推荐|耳机|键盘|保温杯|充电宝|什么好|哪款/, greet: /在吗|你好|哈喽|hi|hello|您好/ }
  },
  ja: {
    docTitle: "ECCS スマートカスタマー", title: "ECCS スマートカスタマー", status: "オンライン · 即返信",
    placeholder: "ご質問を入力してください…（Enterで送信）", hint: "AI スマートエージェント自動応対 · 平均応答 1.5s",
    thinking: "エージェントが考え中…", replied: "スマートエージェントが返信しました", clearTip: "会話を消去",
    q1: "注文はどこ？", q2: "返品方法は？", q3: "イヤホンのおすすめ",
    greet: "こんにちは〜<b>ECCS スマートカスタマー</b>です。24時間対応しております。<br><span class='em'>配送照会</span>・<span class='em'>返品・交換</span>・<span class='em'>商品のおすすめ</span>まで、何なりとお申し付けくださいませ。",
    switched: "日本語に切り替えました。何かお手伝いできますか？",
    cleared: "会話を消去しました。配送照会・返品・商品のおすすめなど、お気軽にどうぞ。",
    card: { order: "ご注文", carrier: "順豊エクスプレス", reco: "おすすめ · 商品ライブラリから", steps: ["支払い済み", "輸送中", "配達中", "受取済み"], paidAt: "昨日 15:02 支払い済み" },
    reply: {
      logistics: "ご注文は現在 <span class='em'>「広州転送センター」</span> を通過中です。明日 18:00 までに到着予定で、配達時にはSMSでお知らせいたします〜",
      returns: "承知いたしました〜対象のご注文は <span class='em'>7日間の無条件返品</span> 期間内です。アフター受付 <span class='em'>#SA-2035</span> を発行いたしました。<br>① 返金のみ（元の支払い方法へ）　② 交換（送料無料・優先発送）　③ 返品・返金",
      reco: "ご要望に合わせて人気の3商品をご提案します。イチオシは1つ目、ノイズキャンセリング搭載で装着感も抜群です：",
      greet: "こんにちは〜ECCS の AI スマートカスタマーです。配送照会・返品交換・商品のおすすめが可能です。ご用件をお聞かせください〜",
      fallback: "承知しました〜こちらで対応可能です。<br>「注文はどこ / 返品方法 / イヤホンのおすすめ」などとお試しください。"
    },
    re: { logistics: /配送|どこ|荷物|発送|注文|追跡|届く|輸送/, returns: /返品|交換|返金|キャンセル|壊れ|不良/, reco: /おすすめ|推薦|薦め|イヤホン|ヘッドホン|キーボード|水筒|ボトル|バッテリー|どれ/, greet: /こんにちは|こんばんは|おはよう|はじめまして|在吗/ }
  }
};

let lang = localStorage.getItem("eccs-lang") || "zh";
const L = () => I18N[lang];

/* ---------- 气泡渲染 ---------- */
const msgs = $("#msgs");
const scrollBottom = () => msgs.scrollTop = msgs.scrollHeight;

function addMsg(who, html, cardHTML) {
  const div = document.createElement("div");
  div.className = `msg ${who}`;
  div.innerHTML = `
    <div class="avatar">絵</div>
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
  div.innerHTML = `<div class="avatar">絵</div><div style="min-width:0"><div class="bubble"><i></i><i></i><i></i></div></div>`;
  msgs.appendChild(div); scrollBottom();
  return div;
}

/* ---------- 卡片渲染（数据已按当前语言本地化） ---------- */
const orderCard = (o) => `
  <div class="card-title"><svg viewBox="0 0 24 24"><path d="M3 7h11v8H3zM14 10h4l3 3v2h-7z"/><circle cx="7" cy="17.4" r="1.6"/><circle cx="17.4" cy="17.4" r="1.6"/></svg>${L().card.order} ${o.order_no} · ${o.carrier}</div>
  <div class="order-row">
    <img src="${o.product.img}" alt="">
    <div><b>${o.product.name}</b><div class="sub">¥${o.product.price} × ${o.qty} · ${o.paid_at}</div></div>
  </div>
  <div class="track">
    ${o.steps.map(s => `<span class="tp ${s.state}">${s.label}</span>`).join("")}
  </div>`;

const recoCard = (items) => `
  <div class="card-title"><svg viewBox="0 0 24 24"><path d="m12 3 2.6 5.3L20 9l-4 3.8.9 5.6L12 15.9 7.1 18.4 8 12.8 4 9l5.4-.7z"/></svg>${L().card.reco}</div>
  <div class="link-row">${items.map(p => `
    <div class="prod-card"><img src="${p.img}" alt="${p.name}"><b>${p.name}</b><div class="price"><small>¥</small>${p.price}</div></div>`).join("")}
  </div>`;

function cardFrom(a) {
  if (!a || !a.data) return "";
  if (a.intent === "order") return orderCard(a.data);
  if (a.intent === "recommend" && Array.isArray(a.data.items)) return recoCard(a.data.items);
  return "";
}

/* ---------- 本地演示回答（后端不可达时的兜底，双语） ---------- */
const ORDER_STATES = ["done", "cur", "", ""];

function localAnswer(q) {
  const T = L(), s = q.toLowerCase();
  const orderData = () => ({
    order_no: "2026081200012", carrier: T.card.carrier, paid_at: T.card.paidAt,
    qty: 1, total: 299,
    steps: ORDER_STATES.map((st, i) => ({ label: T.card.steps[i], state: st })),
    product: { name: PRODUCTS.earbuds[lang], price: PRODUCTS.earbuds.price, img: PRODUCTS.earbuds.img }
  });
  const recoData = () => ({ items: [PRODUCTS.earbuds, PRODUCTS.keyboard, PRODUCTS.power].map(p => ({ name: p[lang], price: p.price, img: p.img })) });

  if (T.re.logistics.test(s)) return { reply: T.reply.logistics, intent: "order", data: orderData() };
  if (T.re.returns.test(s))   return { reply: T.reply.returns, intent: "none", data: null };
  if (T.re.reco.test(s))      return { reply: T.reply.reco, intent: "recommend", data: recoData() };
  if (T.re.greet.test(s))     return { reply: T.reply.greet, intent: "none", data: null };
  return { reply: T.reply.fallback, intent: "none", data: null };
}

/* ---------- 后端桥接：窗口输入 → Python Agent（/api/ask） ---------- */
/* 会话 ID：浏览器维度持久化（localStorage），替代写死的 "demo"，多用户互不串台 */
const SID_KEY = "eccs-sid";
function sessionId() {
  let sid = localStorage.getItem(SID_KEY);
  if (!sid) {
    sid = (crypto.randomUUID ? crypto.randomUUID() : `s-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    localStorage.setItem(SID_KEY, sid);
  }
  return sid;
}

async function askBackend(q) {
  const res = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: q, session_id: sessionId(), lang })
  });
  if (!res.ok) return null;
  const j = await res.json();
  return (j && j.reply) ? j : null;
}

/* 后端卡片数据（中文）→ 当前语言；本地兜底数据已是本地语言，同样幂等 */
function localize(a) {
  if (!a || !a.data) return a;
  const d = a.data;
  if (a.intent === "order") {
    if (Array.isArray(d.steps)) d.steps = d.steps.map((s, i) => ({ label: L().card.steps[i] ?? s.label, state: s.state }));
    if (d.product && d.product.name && lang === "ja") d.product.name = NAME_ZH2JA[d.product.name] || d.product.name;
    if (d.paid_at && lang === "ja") d.paid_at = d.paid_at.replace("昨天", "昨日").replace("付款", "支払い済み");
  }
  if (a.intent === "recommend" && Array.isArray(d.items) && lang === "ja") {
    d.items = d.items.map(it => ({ ...it, name: NAME_ZH2JA[it.name] || it.name }));
  }
  return a;
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
  $("#hint").textContent = L().thinking;

  let a = null;
  try { a = await askBackend(q); } catch (e) { a = null; }   // 后端不可达 → 本地演示
  if (!a || !a.reply) a = localAnswer(q);
  localize(a);

  await wait(DELAY());
  typing.remove();
  addMsg("ai", a.reply, cardFrom(a));
  $("#hint").textContent = L().replied;
  busy = false;
}

/* ---------- 语言一键切换 ---------- */
function setLang(l, announce = true) {
  if (l === lang && announce) return;
  lang = l;
  localStorage.setItem("eccs-lang", l);
  document.documentElement.lang = (l === "ja") ? "ja" : "zh-CN";
  document.title = L().docTitle;

  $("#langZH").classList.toggle("active", l === "zh");
  $("#langJA").classList.toggle("active", l === "ja");
  $("#langZH").setAttribute("aria-pressed", String(l === "zh"));
  $("#langJA").setAttribute("aria-pressed", String(l === "ja"));

  $$("[data-i18n]").forEach(el => { const k = el.dataset.i18n; if (L()[k] !== undefined) el.textContent = L()[k]; });
  $$("[data-i18n-ph]").forEach(el => { el.placeholder = L()[el.dataset.i18nPh]; });
  $$("[data-i18n-title]").forEach(el => { el.title = L()[el.dataset.i18nTitle]; });
  $("#hint").textContent = L().hint;

  if (announce) addMsg("ai", L().switched);
}

/* ---------- 工具 ---------- */
function escapeHTML(s) {
  return s.replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const autoGrow = t => { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 120) + "px"; };

/* ---------- 事件 ---------- */
$("#sendBtn").addEventListener("click", send);
input.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
input.addEventListener("input", () => autoGrow(input));
$$(".quick").forEach(b => b.addEventListener("click", () => { input.value = L()[b.dataset.qKey]; autoGrow(input); send(); }));
$("#clearBtn").addEventListener("click", () => {
  // 真清空：后端删除该会话的 checkpoint 线程与摘要；后端不可达时仅本地清空（不阻塞）
  fetch("/api/clear", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId() })
  }).catch(() => {});
  msgs.innerHTML = "";
  addMsg("ai", L().cleared);
});
$("#langZH").addEventListener("click", () => setLang("zh"));
$("#langJA").addEventListener("click", () => setLang("ja"));

/* ---------- 启动 ---------- */
setLang(lang, false);
addMsg("ai", L().greet);
