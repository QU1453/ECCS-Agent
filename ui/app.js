/* =====================================================================
   ECCS 卖家工作台 · 双工作台（选品 / Listing）× 中/日一键切换
   - 每个工作台独立聊天流 + 独立谈话会话（session_id）
   - 「结束谈话」→ POST /api/conversation/end 触发一级总结管线
   - 后端桥接：POST /api/ask → Python 多智能体（不可达时本地演示兜底）
   ===================================================================== */
"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const IMG = p => "https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=" + p + "&image_size=square";
const now = () => { const d = new Date(); return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; };
const wait = ms => new Promise(r => setTimeout(r, ms));
const DELAY = () => 800 + Math.random() * 600;

/* ---------- 商品演示数据（中/日双语，推荐/订单卡片用） ---------- */
const PRODUCTS = {
  earbuds:  { zh: "云感无线蓝牙耳机 Pro · 半入耳", ja: "雲感ワイヤレスイヤホン Pro · 半インナー", price: 299, img: IMG("studio%20product%20photo%20minimalist%20white%20wireless%20earbuds%20open%20charging%20case%20soft%20warm%20beige%20background") },
  keyboard: { zh: "奶糖机械键盘 87 键 · 奶油橙",   ja: "キャンディメカニカルキーボード 87キー · クリームオレンジ", price: 459, img: IMG("studio%20product%20photo%20retro%20cream%20mechanical%20keyboard%20warm%20orange%20keycaps%20soft%20beige%20background") },
  tumbler:  { zh: "山雾保温杯 450ml · 燕麦奶",     ja: "山霧マグボトル 450ml · オートミルク", price: 129, img: IMG("studio%20product%20photo%20cream%20matte%20insulated%20tumbler%20with%20lid%20warm%20beige%20background") },
  power:    { zh: "珊瑚移动电源 10000mAh · 快充",  ja: "サンゴモバイルバッテリー 10000mAh · 急速充電", price: 189, img: IMG("studio%20product%20photo%20slim%20coral%20orange%20power%20bank%20warm%20neutral%20background") }
};
const NAME_ZH2JA = Object.fromEntries(Object.values(PRODUCTS).map(p => [p.zh, p.ja]));

/* ---------- 多语言文案 ---------- */
const I18N = {
  zh: {
    docTitle: "ECCS 卖家工作台", title: "ECCS 卖家工作台", status: "在线 · 秒回",
    placeholder: "输入选品/上架需求…（Enter 发送）", hint: "AI 多智能体工作台 · 选品 + Listing 上架",
    thinking: "智能体思考中…", replied: "智能体已回复", clearTip: "清空对话", endTalk: "结束谈话",
    tabResearch: "选品工作台", tabListing: "Listing 工作台",
    r1: "帮我选个充电宝", r2: "对比蓝牙耳机供应商", r3: "充电宝利润测算",
    l1: "给云感耳机写 Listing", l2: "检查主图合规", l3: "云感耳机定价建议",
    greetResearch: "您好，这里是<b>选品工作台</b>。<br>我可以帮您做 <span class='em'>四步选品验证</span>（需求/竞争/利润）与 <span class='em'>供应商对比</span>，直接说品类即可～",
    greetListing: "您好，这里是<b>Listing 工作台</b>。<br>我可以帮您 <span class='em'>起草标题/五点/Search Terms</span>、<span class='em'>图片合规自检</span>、<span class='em'>定价与 FBA 建议</span>。",
    switched: "已切换为中文。有什么可以帮您？",
    cleared: "已清空对话。需要帮忙做选品验证或写 Listing 吗？",
    endDone: "本次谈话已结束并完成 <span class='em'>总结归档</span>（多轮记忆与长期画像已更新）。已为您开启新一轮谈话～",
    endFail: "结束谈话未成功（后端不可达），请稍后重试。",
    order: "订单", carrier: "顺丰速运", reco: "智能推荐 · 商品库命中", steps: ["已付款", "运输中", "派送中", "已签收"], paidAt: "昨天 15:02 付款",
    card: {
      verdict: "选品结论", score: "四步得分", passed: "通过", failed: "未通过",
      supplier: "供应商对比", recommend: "综合推荐", moq: "起订量", unitPrice: "单价", lead: "交期",
      draft: "Listing 草稿", bullets: "五点描述", terms: "Search Terms", tips: "合规提示",
      images: "图片合规自检", price: "定价建议", suggested: "建议售价", floor: "保本底价", fulfill: "履约建议", mode: "建议方式", batch: "首批备货"
    }
  },
  ja: {
    docTitle: "ECCS セラーコンソール", title: "ECCS セラーコンソール", status: "オンライン · 即返信",
    placeholder: "選品・出品のご要望を入力…（Enterで送信）", hint: "AI マルチエージェント · 選品 + 出品支援",
    thinking: "エージェントが考え中…", replied: "エージェントが返信しました", clearTip: "会話を消去", endTalk: "会話を終了",
    tabResearch: "選品ワークベンチ", tabListing: "Listing ワークベンチ",
    r1: "モバイルバッテリーを選品", r2: "イヤホンの仕入れ先を比較", r3: "利益を試算",
    l1: "イヤホンの Listing 作成", l2: "メイン画像をチェック", l3: "価格を提案",
    greetResearch: "こんにちは。こちらは<b>選品ワークベンチ</b>です。<br><span class='em'>需要・競合・利益</span>の4段階検証と<span class='em'>仕入れ先比較</span>をサポートします。カテゴリをお知らせください〜",
    greetListing: "こんにちは。こちらは<b>Listing ワークベンチ</b>です。<br><span class='em'>タイトル・箇条書き・Search Terms</span>の作成、<span class='em'>画像規約チェック</span>、<span class='em'>価格・FBA 提案</span>を行います。",
    switched: "日本語に切り替えました。何かお手伝いできますか？",
    cleared: "会話を消去しました。選品検証や Listing 作成をお気軽にどうぞ。",
    endDone: "今回の会話は終了し、<span class='em'>要約を保存</span>しました（多輪記憶と長期プロファイルを更新済み）。新しい会話を開始しました〜",
    endFail: "会話の終了に失敗しました（バックエンド未接続）。後ほどお試しください。",
    order: "ご注文", carrier: "順豊エクスプレス", reco: "おすすめ · 商品ライブラリから", steps: ["支払い済み", "輸送中", "配達中", "受取済み"], paidAt: "昨日 15:02 支払い済み",
    card: {
      verdict: "選品結論", score: "4段階スコア", passed: "合格", failed: "不合格",
      supplier: "仕入れ先比較", recommend: "総合おすすめ", moq: "最小ロット", unitPrice: "単価", lead: "納期",
      draft: "Listing 下書き", bullets: "箇条書き", terms: "Search Terms", tips: "規約ヒント",
      images: "画像規約チェック", price: "価格提案", suggested: "推奨価格", floor: "損益分岐価格", fulfill: "フルフィルメント提案", mode: "推奨方式", batch: "初回仕入れ"
    }
  }
};

let lang = localStorage.getItem("eccs-lang") || "zh";
const L = () => I18N[lang];

/* ---------- 双工作台配置 ---------- */
const BENCHES = {
  research: { msgsId: "msgs-research", sidKey: "eccs-sid-research", greetKey: "greetResearch" },
  listing:  { msgsId: "msgs-listing",  sidKey: "eccs-sid-listing",  greetKey: "greetListing" }
};
let activeBench = "research";

/* ---------- 气泡渲染（按工作台） ---------- */
const msgsEl = bench => $(`#${BENCHES[bench].msgsId}`);
const scrollBottom = bench => { const el = msgsEl(bench); el.scrollTop = el.scrollHeight; };

function addMsg(bench, who, html, cardHTML) {
  const el = msgsEl(bench);
  const div = document.createElement("div");
  div.className = `msg ${who}`;
  div.innerHTML = `
    <div class="avatar">絵</div>
    <div style="min-width:0">
      <div class="bubble">${html}${cardHTML ? `<div class="card">${cardHTML}</div>` : ""}</div>
      <div class="time">${now()}</div>
    </div>`;
  el.appendChild(div);
  scrollBottom(bench);
  return div;
}
function showTyping(bench) {
  const el = msgsEl(bench);
  const div = document.createElement("div");
  div.className = "msg ai typing";
  div.innerHTML = `<div class="avatar">絵</div><div style="min-width:0"><div class="bubble"><i></i><i></i><i></i></div></div>`;
  el.appendChild(div); scrollBottom(bench);
  return div;
}

/* ---------- 卡片渲染（订单 / 推荐 / 选品 / 供应商 / Listing） ---------- */
const orderCard = (o) => `
  <div class="card-title"><svg viewBox="0 0 24 24"><path d="M3 7h11v8H3zM14 10h4l3 3v2h-7z"/><circle cx="7" cy="17.4" r="1.6"/><circle cx="17.4" cy="17.4" r="1.6"/></svg>${L().order} ${o.order_no} · ${o.carrier}</div>
  <div class="order-row">
    <img src="${o.product.img}" alt="">
    <div><b>${o.product.name}</b><div class="sub">¥${o.product.price} × ${o.qty} · ${o.paid_at}</div></div>
  </div>
  <div class="track">
    ${(o.steps || []).map(s => `<span class="tp ${s.state}">${s.label}</span>`).join("")}
  </div>`;

const recoCard = (items) => `
  <div class="card-title"><svg viewBox="0 0 24 24"><path d="m12 3 2.6 5.3L20 9l-4 3.8.9 5.6L12 15.9 7.1 18.4 8 12.8 4 9l5.4-.7z"/></svg>${L().card.reco}</div>
  <div class="link-row">${items.map(p => `
    <div class="prod-card"><img src="${p.img}" alt="${p.name}"><b>${p.name}</b><div class="price"><small>¥</small>${p.price}</div></div>`).join("")}
  </div>`;

const checkIcon = ok => ok
  ? `<span class="ck ok">✓</span>`
  : `<span class="ck bad">✗</span>`;

const reportCard = (d) => `
  <div class="card-title ck-title">${L().card.verdict} · ${escapeHTML(d.category || "")} <span class="score-tag">${escapeHTML(d.score || "")}</span><span class="verdict ${d.verdict === "建议推进" ? "go" : "warn"}">${escapeHTML(d.verdict || "")}</span></div>
  <div class="check-list">
    ${Object.entries(d.steps || {}).map(([k, v]) => `
      <div class="check-row">${checkIcon(v.passed)}<span class="ck-name">${escapeHTML(k)}</span>
        <span class="ck-detail">${Object.entries(v).filter(([x]) => x !== "passed").map(([x, b]) => `${escapeHTML(x)}:${typeof b === "boolean" ? (b ? "✓" : "✗") : escapeHTML(String(b))}`).join(" · ")}</span>
      </div>`).join("")}
  </div>`;

const supplierCard = (d) => `
  <div class="card-title ck-title">${L().card.supplier} · ${escapeHTML(d.keyword || "")}</div>
  <table class="sup-table">
    <tr><th>供应商</th><th>${L().card.moq}</th><th>${L().card.unitPrice}</th><th>${L().card.lead}</th><th>评分</th></tr>
    ${(d.rows || []).map(r => `
      <tr class="${r.name === d.recommend ? "best" : ""}"><td>${r.name === d.recommend ? "★ " : ""}${escapeHTML(r.name)}<small>${escapeHTML(r.city || "")}</small></td>
      <td>${r.moq} 件</td><td>¥${r.unit_price}</td><td>${r.lead_days} 天</td><td>${r.rating}</td></tr>`).join("")}
  </table>
  <div class="recommend-line">${L().card.recommend}：<b>${escapeHTML(d.recommend || "")}</b>${d.reason ? ` —— ${escapeHTML(d.reason)}` : ""}</div>`;

const listingCard = (d) => `
  <div class="card-title ck-title">${L().card.draft} · ${escapeHTML(d.product || "")} <span class="score-tag">标题 ${d.title_len || 0} 字符</span></div>
  <div class="draft-title">${escapeHTML(d.title || "")}</div>
  <div class="sub-head">${L().card.bullets}</div>
  <ol class="bullets">${(d.bullets || []).map(b => `<li>${escapeHTML(b)}</li>`).join("")}</ol>
  <div class="sub-head">${L().card.terms}</div>
  <div class="terms">${escapeHTML(d.search_terms || "")}</div>
  <div class="tips">${(d.tips || []).map(t => `<span>${escapeHTML(t)}</span>`).join("")}</div>`;

const imageCard = (d) => `
  <div class="card-title ck-title">${L().card.images} <span class="score-tag">${d.passed_count}/${d.total}</span></div>
  <div class="check-list">
    ${(d.detail || []).map(x => `
      <div class="check-row">${checkIcon(x.passed)}<span class="ck-name">图 ${x.image_no}</span>
        <span class="ck-detail">${x.white_bg ? "白底✓" : "白底✗"} · 占比${x.ratio_ok ? "✓" : "✗"} · ${x.no_text_watermark ? "无文字✓" : "有文字✗"}</span>
      </div>`).join("")}
  </div>`;

const priceCard = (d) => `
  <div class="card-title ck-title">${L().card.price} · ${escapeHTML(d.product || "")}</div>
  <div class="price-line"><span class="price-big">¥${d.suggested}</span><span class="price-sub">${L().card.suggested}</span></div>
  <div class="price-meta">竞品参考 ¥${d.competitor_ref} · ${L().card.floor} <b>¥${d.min_break_even}</b></div>
  <div class="tips">${d.hint ? `<span>${escapeHTML(d.hint)}</span>` : ""}</div>`;

const fulfillCard = (d) => `
  <div class="card-title ck-title">${L().card.fulfill} · ${escapeHTML(d.product || "")}</div>
  <div class="price-line"><span class="price-big">${escapeHTML(d.suggested_mode || "")}</span><span class="price-sub">${L().card.mode}</span></div>
  <div class="price-meta">${L().card.batch}：<b>${d.first_batch} 件</b></div>
  <div class="tips">${d.hint ? `<span>${escapeHTML(d.hint)}</span>` : ""}</div>`;

function cardFrom(a) {
  if (!a || !a.data) return "";
  if (a.intent === "order") return orderCard(a.data);
  if (a.intent === "recommend" && Array.isArray(a.data.items)) return recoCard(a.data.items);
  const t = a.data.type;
  if (t === "research_report") return reportCard(a.data);
  if (t === "supplier_compare") return supplierCard(a.data);
  if (t === "listing_draft") return listingCard(a.data);
  if (t === "image_check") return imageCard(a.data);
  if (t === "price_strategy") return priceCard(a.data);
  if (t === "fulfillment") return fulfillCard(a.data);
  return "";
}

/* ---------- 本地演示回答（后端不可达时的兜底，双语） ---------- */
function localAnswer(q) {
  const T = L(), s = q.toLowerCase();
  const orderData = () => ({
    order_no: "2026081200012", carrier: T.carrier, paid_at: T.paidAt,
    qty: 1, total: 299,
    steps: T.steps.map((label, i) => ({ label, state: ["done", "cur", "", ""][i] })),
    product: { name: PRODUCTS.earbuds[lang], price: PRODUCTS.earbuds.price, img: PRODUCTS.earbuds.img }
  });
  const recoData = () => ({ items: [PRODUCTS.earbuds, PRODUCTS.keyboard, PRODUCTS.power].map(p => ({ name: p[lang], price: p.price, img: p.img })) });

  if (/(物流|快递|到哪|发货|订单|单号|签收|配送|荷物|注文|追跡|届く)/.test(s)) {
    return { reply: T.greetResearch, intent: "order", data: orderData() };
  }
  if (/(供应商|1688|阿里|货源|进货|采购|仕入れ)/.test(s)) {
    return { reply: "已为您找到候选货源（演示数据），详见对比卡片：", intent: "research",
      data: { type: "supplier_compare", keyword: "蓝牙耳机", recommend: "深圳声学智造",
        reason: "评分 4.9 且综合分最高", rows: [
          { name: "深圳声学智造", city: "深圳", moq: 60, unit_price: 45.0, lead_days: 9, rating: 4.9 },
          { name: "东莞音频电子", city: "东莞", moq: 100, unit_price: 39.0, lead_days: 12, rating: 4.5 },
          { name: "义乌数码港·鑫声", city: "义乌", moq: 40, unit_price: 48.0, lead_days: 6, rating: 4.4 }] } };
  }
  if (/(选品|选个|热销|爆款|利润|竞争|需求|選品|利益)/.test(s)) {
    return { reply: "「云感耳机」选品四步结论：<b>建议推进</b>（3/3）。", intent: "research",
      data: { type: "research_report", category: "云感耳机", score: "3/3", verdict: "建议推进",
        steps: {
          需求: { passed: true, "搜索量≥3000": true, "售价$20~$70": true, "重量<2lb": true },
          竞争: { passed: true, "首页评分≤4.3": true, "平均评论≤500": true },
          利润: { passed: true, "margin": 0.34, "profit_per_unit": 17.6 } } } };
  }
  if (/(listing|上架|标题|五点|出品)/.test(s)) {
    return { reply: "「云感耳机」Listing 草稿已生成（见卡片）：", intent: "listing",
      data: { type: "listing_draft", product: "云感耳机",
        title: "ECCS Wireless Earbuds with ANC HiFi Stereo / 36H Playtime / IPX5 for Sports & Commuting",
        title_len: 80, bullets: [
          "主动降噪，通勤地铁一戴安静：双馈 ANC 降噪深度 -35dB，专注不被打扰。",
          "36 小时长续航：单次 8h + 充电盒再续 28h，出差一周不用带线。",
          "云感半入耳，久戴不痛：单耳仅 3.8g，人体工学贴合，跑步也不掉。",
          "HiFi 双单元：10mm 动圈 + 高解析解码，低音有量、人声清晰。",
          "IPX5 防水：运动流汗、小雨天都可以放心用。"],
        search_terms: "bluetooth earphones anc wireless earbuds sport headset true wireless ipx5",
        tips: ["标题 ≤75 字符（亚马逊 2025 新规）", "五点每点首词大写、先答核心问题"] } };
  }
  if (/(定价|售价|価格)/.test(s) && (/(云感耳机|earbuds)/.test(s) || !/list/.test(s))) {
    return { reply: "「云感无线蓝牙耳机 Pro · 半入耳」定价建议：¥284（略低于竞品做首发）。", intent: "listing",
      data: { type: "price_strategy", product: "云感无线蓝牙耳机 Pro · 半入耳", competitor_ref: 299, suggested: 284, min_break_even: 233, hint: "低于 233 元将跌破 30% 净利率红线。" } };
  }
  return { reply: T.greetResearch, intent: "none", data: null };
}

/* ---------- 后端桥接：窗口输入 → Python 多智能体 ---------- */
const SID_KEYS = { research: "eccs-sid-research", listing: "eccs-sid-listing" };
function sidOf(bench) { return localStorage.getItem(SID_KEYS[bench]) || ""; }
function storeSid(bench, sid) { localStorage.setItem(SID_KEYS[bench], sid); }

async function ensureSession(bench, force = false) {
  if (!force && sidOf(bench)) return sidOf(bench);
  try {
    const res = await fetch("/api/conversation/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: "default" })
    });
    if (!res.ok) throw new Error("bad");
    const j = await res.json();
    if (j && j.session_id) { storeSid(bench, j.session_id); return j.session_id; }
  } catch (e) { /* 后端不可达 → 本地生成 */ }
  const sid = (crypto.randomUUID ? crypto.randomUUID() : `s-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  storeSid(bench, sid);
  return sid;
}

async function askBackend(q, bench) {
  const sid = await ensureSession(bench);
  const res = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: q, session_id: sid, user_id: "default", lang })
  });
  if (!res.ok) return null;
  const j = await res.json();
  return (j && j.reply) ? j : null;
}

/* 后端卡片数据（中文）→ 当前语言（仅订单/推荐卡片需要本地化） */
function localize(a) {
  if (!a || !a.data) return a;
  const d = a.data;
  if (a.intent === "order") {
    if (Array.isArray(d.steps)) d.steps = d.steps.map((s, i) => ({ label: L().steps[i] ?? s.label, state: s.state }));
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
  const bench = activeBench;

  addMsg(bench, "user", escapeHTML(q));
  const typing = showTyping(bench);
  $("#hint").textContent = L().thinking;

  let a = null;
  try { a = await askBackend(q, bench); } catch (e) { a = null; }   // 后端不可达 → 本地演示
  if (!a || !a.reply) a = localAnswer(q);
  localize(a);

  await wait(DELAY());
  typing.remove();
  addMsg(bench, "ai", a.reply, cardFrom(a));
  $("#hint").textContent = L().replied;
  busy = false;
}

/* ---------- 结束本次谈话：总结归档 + 开启新谈话 ---------- */
async function endConversation() {
  const bench = activeBench;
  const sid = sidOf(bench);
  let ok = !!sid;
  if (sid) {
    try {
      const res = await fetch("/api/conversation/end", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sid, user_id: "default" })
      });
      ok = res.ok;
    } catch (e) { ok = false; }
  }
  await ensureSession(bench, true);   // 换新谈话 ID（旧的已归档）
  addMsg(bench, "ai", L()[ok ? "endDone" : "endFail"]);
}

/* ---------- 工作台切换 ---------- */
function switchBench(bench) {
  if (bench === activeBench) return;
  activeBench = bench;
  $$(".tab").forEach(b => b.classList.toggle("active", b.dataset.bench === bench));
  $$(".msgs").forEach(el => el.classList.remove("active"));
  msgsEl(bench).classList.add("active");
  $("#chips-research").hidden = bench !== "research";
  $("#chips-listing").hidden = bench !== "listing";
  $("#input").placeholder = L().placeholder;
  scrollBottom(bench);
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

  $$("[data-i18n]").forEach(el => { const k = el.dataset.i18n; if (L()[k] !== undefined) el.textContent = L()[k]; });
  $$("[data-i18n-ph]").forEach(el => { el.placeholder = L()[el.dataset.i18nPh]; });
  $$("[data-i18n-title]").forEach(el => { el.title = L()[el.dataset.i18nTitle]; });
  $("#hint").textContent = L().hint;

  if (announce) addMsg(activeBench, "ai", L().switched);
}

/* ---------- 工具 ---------- */
function escapeHTML(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const autoGrow = t => { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 120) + "px"; };

/* ---------- 事件 ---------- */
$("#sendBtn").addEventListener("click", send);
input.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
input.addEventListener("input", () => autoGrow(input));
$$(".tab").forEach(tab => {
  tab.addEventListener("click", () => { switchBench(tab.dataset.bench); ensureSession(tab.dataset.bench); });
});
$$(".quick").forEach(b => b.addEventListener("click", () => { input.value = L()[b.dataset.qKey] || b.textContent; autoGrow(input); send(); }));
$("#endBtn").addEventListener("click", endConversation);
$("#clearBtn").addEventListener("click", () => {
  // 真清空：后端删除该工作台会话的 checkpoint 线程与摘要；后端不可达时仅本地清空
  const sid = sidOf(activeBench);
  if (sid) {
    fetch("/api/clear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sid })
    }).catch(() => {});
  }
  msgsEl(activeBench).innerHTML = "";
  addMsg(activeBench, "ai", L().cleared);
});
$("#langZH").addEventListener("click", () => setLang("zh"));
$("#langJA").addEventListener("click", () => setLang("ja"));

/* ---------- 启动 ---------- */
setLang(lang, false);
addMsg("research", "ai", L().greetResearch);
addMsg("listing", "ai", L().greetListing);
ensureSession("research");
ensureSession("listing");