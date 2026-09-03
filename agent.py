# -*- coding: utf-8 -*-
"""ECCS Agent：单文件多智能体调度（Supervisor 路由 + 日语 + 专职 specialist）。

结构（相比原单智能体版本的升级）：
- answer() 先做「意图 + 语言」两级分类 → 路由到对应 specialist；
- 每个 specialist 拥有独立的 SYSTEM_PROMPT 与工具子集，Graph 按需懒加载缓存；
- 人工接管钩子：命中 human intent 直接返回，不走 LLM；
- 配置了 OPENAI_API_KEY 时：LLM specialist + LLM 意图精分；
- 未配置 Key 或调用失败：classic_reply 本地兜底（中日双语关键词路由，中文原分支一字未动）。

安全约定：本模块从不保存密钥，OPENAI_API_KEY 只从环境变量 / .env 读取。
"""
from __future__ import annotations

import json
import re

from tools import (
    handle_return,
    lookup_order,
    query_order_info,
    recommend_for,
    recommend_products,
    register_return,
    track_logistics,
)

# ---- LangGraph 相关为可选依赖：装不上也能以"本地兜底模式"运行 -------------------
try:
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent

    _HAS_LANGGRAPH = True
except Exception:  # pragma: no cover - 离线环境 / 未安装依赖时
    _HAS_LANGGRAPH = False
    create_react_agent = None
    ChatOpenAI = None


# ============================================================================
# 1. 意图分类：语言检测 → 正则粗分 →（可选）LLM 精分
# ============================================================================

_JA_KANA_RE = re.compile(r"[ぁ-んァ-ヶー]")


def _detect_lang(q: str) -> str:
    """命中日文假名/片假名/长音 → ja，否则 zh。"""
    return "ja" if _JA_KANA_RE.search(q or "") else "zh"


def _classify_by_regex(q: str) -> tuple[str, str]:
    """正则粗分 (intent, lang)，优先级从上到下，命中即返回。"""
    s = (q or "").lower()
    lang = _detect_lang(q or "")

    # human（转人工）
    if re.search(r"人工|真人|客服|听不懂|转人|帮我接|找客服", s) or (
        lang == "ja" and re.search(r"オペレーター|人間|わかりません|繋いで|つないで", s)
    ):
        return "human", lang

    # after_sales（售后 / 退换 / 退款）
    if re.search(r"退|换|退款|售后|质量|坏了|瑕疵|修", s) or (
        lang == "ja" and re.search(r"返品|交換|返金|不良|欠陥|修理|へんぴん|こうかん", s)
    ):
        return "after_sales", lang

    # recommend（商品推荐）
    if re.search(
        r"推荐|什么好|哪款|买什么|耳机|键盘|保温杯|充电宝|选哪个",
        s,
    ) or (
        lang == "ja"
        and re.search(r"おすすめ|人気|どれが|イヤホン|キーボード|水筒|モバイルバッテリー", s)
    ):
        return "recommend", lang

    # order（订单 / 物流）
    if re.search(r"物流|快递|到哪|发货|订单|单号|签收|付款|到了|配送", s) or (
        lang == "ja" and re.search(r"注文|配送|到着|追跡|発送|荷物|ちゅうもん|はいそう", s)
    ):
        return "order", lang

    # chitchat（问候 / 闲聊）
    if re.search(r"在吗|你好|哈喽|hi|hello|谢谢|感谢|再见|拜拜", s) or (
        lang == "ja"
        and re.search(r"こんにちは|はじめまして|ありがとう|さようなら|すみません|ごめんなさい", s)
    ):
        return "chitchat", lang

    return "unknown", lang


def _classify_by_llm(q: str, lang: str, llm) -> str:
    """仅在 regex 返回 unknown 且 llm 可用时调用，单次纯分类，失败回 unknown。"""
    if llm is None:
        return "unknown"
    if lang == "ja":
        prompt = (
            "ユーザーの質問を次の6種類のいずれかに分類し、"
            'JSON {"intent":"..."} だけを返してください。'
            "候補：order / after_sales / recommend / chitchat / human / unknown。\n"
            f"入力：{q}"
        )
    else:
        prompt = (
            "将用户问题分类为以下 6 种之一，只返回 JSON {\"intent\":\"...\"}。"
            "候选：order / after_sales / recommend / chitchat / human / unknown。\n"
            f"用户输入：{q}"
        )
    try:
        resp = llm.invoke([{"role": "user", "content": prompt}])
        content = getattr(resp, "content", str(resp)) or ""
        # 解析 JSON：优先找大括号包裹，兜底整段文本
        m = re.search(r"\{[^}]*\}", content)
        payload = json.loads(m.group(0) if m else content)
        intent = str(payload.get("intent", "unknown")).strip()
        if intent in {"order", "after_sales", "recommend", "chitchat", "human", "unknown"}:
            return intent
        return "unknown"
    except Exception:  # noqa: BLE001 - 任何异常都安全兜底
        return "unknown"


def _build_human_reply(lang: str) -> dict:
    """人工接管结构化响应，中/日两版。"""
    if lang == "ja":
        reply = (
            "承知いたしました。オペレーターにお繋ぎいたしますので、"
            "少々お待ちくださいませ。担当者がまもなく対応いたします～"
        )
    else:
        reply = "好的，已为您转接人工客服，我们的专员会尽快与您联系～请稍等片刻。"
    return {"reply": reply, "intent": "human", "data": None}


# ============================================================================
# 2. Agent：多 specialist graph 缓存 + 路由调度
# ============================================================================

def _build_react_agent(llm, tools, prompt: str):
    """兼容不同 langgraph 版本：1.x 用 prompt=，旧版用 messages_modifier/state_modifier=。"""
    try:
        return create_react_agent(model=llm, tools=tools, prompt=prompt)
    except TypeError:
        try:
            return create_react_agent(model=llm, tools=tools, messages_modifier=prompt)
        except TypeError:
            return create_react_agent(model=llm, tools=tools, state_modifier=prompt)


# ---- 各 specialist 专用 SYSTEM_PROMPT -----------------------------------------

def _zh_order_prompt() -> str:
    return (
        "你是「ECCS」跨境电商智能客服的【订单/物流专员】，只负责订单查询与物流跟踪。\n"
        "工作方式：\n"
        "- 查询订单基本信息（商品、金额、付款时间、状态）→ 调用 query_order_info(order_no)；\n"
        "- 查询物流轨迹与预计送达时间 → 调用 track_logistics(order_no)；\n"
        "- 若用户没提供订单号：礼貌询问（如「麻烦告诉我一下订单号哦，类似 2026081200012 这种格式」），不要编造单号。\n"
        "回复要求：简洁友好、像真人客服；使用与用户输入相同的语言回复；引用工具返回的金额、地点、时间等事实，不得虚构；若未找到请如实说明并引导核对；不要暴露工具名或 JSON。"
    )


def _zh_after_sales_prompt() -> str:
    return (
        "你是「ECCS」跨境电商智能客服的【售后专员】，只负责退换货、退款、质量投诉。\n"
        "工作方式：\n"
        "- 用户要求办理退换/退款时，调用 handle_return(order_no, reason)，没有订单号先礼貌询问；\n"
        "- 同理心强，先安抚情绪，再主动列出 3 种方案（仅退款 / 换新 / 退货退款）引导用户选择。\n"
        "回复要求：简洁、温暖、同理心；使用用户的语言；引用工具返回的售后单号和退款金额，不得虚构；不要暴露内部实现细节。"
    )


def _zh_recommend_prompt() -> str:
    return (
        "你是「ECCS」跨境电商智能客服的【商品导购】，只负责推荐合适的商品。\n"
        "工作方式：\n"
        "- 调用 recommend_products(keywords)，keywords 为用户需求的关键词列表（如 ['耳机', '降噪']）；\n"
        "- 结合返回的每款商品的 feature（卖点）用自然语言撰写推荐理由，最推荐的放在最前面。\n"
        "回复要求：语气像朋友推荐，每款商品 1-2 句话点明卖点；使用用户的语言；价格与卖点引用工具结果，不要虚构；不要暴露内部细节。"
    )


def _zh_generic_prompt() -> str:
    return (
        "你是「ECCS」跨境电商智能客服 Agent，面向海外消费者，使用与用户输入相同的语言回复。\n"
        "工作方式：根据用户问题，自主决定是否调用工具获取事实，再用自然语言作答：\n"
        "- 查订单/物流 → 先调用 query_order_info / track_logistics（订单号形如 2026081200012）；\n"
        "- 办退换货/退款 → 先调用 handle_return；\n"
        "- 求推荐商品 → 调用 recommend_products，并结合工具返回的商品特点给出理由；\n"
        "- 用户没说订单号：礼貌询问，不要编造单号。\n"
        "回复要求：简洁、友好、像真人客服；引用工具返回的事实，不得虚构；若工具返回未找到如实说明；不要暴露工具名称、JSON 等内部实现细节。"
    )


def _ja_order_prompt() -> str:
    return (
        "あなたは「ECCS」越境EC AIカスタマーサポートの【注文・配送担当】です。注文確認と配送追跡だけを担当してください。\n"
        "対応方法：\n"
        "- 注文内容（商品・金額・支払日時・ステータス）を確認するときは、query_order_info(order_no) を呼び出す；\n"
        "- 配送状況・到着予定日時を確認するときは、track_logistics(order_no) を呼び出す；\n"
        "- 注文番号が不明な場合は、丁寧にお尋ねください（例：「恐れ入りますが、注文番号をお教えいただけますでしょうか。2026081200012 のような形式です。」）。勝手な番号はでっち上げないでください。\n"
        "【最重要】必ず**です・ます体（丁寧語）**で回答してください。金額・場所・日時はツールの結果を使用し、事実をでっち上げないでください。商品名や注文番号はそのまま使って構いませんが、説明文はすべて日本語にしてください。ツール名やJSONは絶対に出力しないでください。"
    )


def _ja_after_sales_prompt() -> str:
    return (
        "あなたは「ECCS」越境EC AIカスタマーサポートの【返品交換担当】です。返品・交換・返金・不良品対応だけを担当してください。\n"
        "対応方法：\n"
        "- 返品・交換・返金の申し出があった場合、handle_return(order_no, reason) を呼び出す；注文番号がない場合はまず丁寧にお尋ねください；\n"
        "- まずお客様の心情に寄り添い、そのあとで選択肢（①返金のみ ②新品交換 ③返品返金）を丁寧に提示してお選びください。\n"
        "【最重要】必ず**です・ます体**で回答してください。受付番号・返金額はツールの結果をそのまま使用。ツール名やJSONは絶対に出力しないでください。"
    )


def _ja_recommend_prompt() -> str:
    return (
        "あなたは「ECCS」越境EC AIカスタマーサポートの【商品案内担当】です。商品の推薦だけを担当してください。\n"
        "対応方法：\n"
        "- recommend_products(keywords) を呼び出してください。keywords はお客様のニーズを表すキーワードのリストです（例：['イヤホン', 'ノイズキャンセリング']）；\n"
        "- ツールが返した各商品の feature を踏まえ、自然な日本語で推薦文を書いてください。一番おすすめの商品を最初に持ってきてください。\n"
        "【最重要】必ず**です・ます体**で回答してください。価格やスペックはツールの結果通りに。ツール名やJSONは絶対に出力しないでください。"
    )


def _ja_generic_prompt() -> str:
    return (
        "あなたは「ECCS」越境ECのAIカスタマーサポートです。日本のお客様向けに、すべて**です・ます体（丁寧語）**で丁寧に回答してください。\n"
        "対応方法：\n"
        "- 注文確認・配送追跡 → query_order_info / track_logistics（注文番号は 2026081200012 のような形式）；\n"
        "- 返品・交換・返金 → handle_return；\n"
        "- 商品推薦 → recommend_products；\n"
        "- 注文番号がない場合は丁寧にお尋ねください。勝手な番号はでっち上げないでください。\n"
        "【絶対ルール】です・ます体を必ず使うこと。金額や日時・場所はツールの事実を使用すること。見つからない場合は正直に「見つかりませんでした」と案内すること。ツール名・JSON・内部実装の詳細は絶対に出力しないこと。"
    )


class Agent:
    """多智能体 Supervisor：意图路由 → 对应 specialist（多 graph 懒加载缓存）。

    对外签名与原单智能体 Agent 100% 兼容：
    - Agent(api_key, base_url=None, model="gpt-4o-mini")
    - .available -> bool
    - .reason -> str
    - .model -> str
    - .answer(question, history=None) -> dict | None
    """

    def __init__(
        self,
        api_key: str | None,
        base_url: str | None = None,
        model: str = "gpt-4o-mini",
    ):
        self.model = model
        self.reason = None  # 初始化失败/未配置的原因（供日志展示）
        self._llm = None
        self._graphs: dict[tuple, object] = {}  # key: (intent, lang)
        self._prompt_cache: dict[tuple, str] = {}

        if not api_key:
            self.reason = "未配置 OPENAI_API_KEY，运行于本地规则兜底模式"
            return
        if not _HAS_LANGGRAPH:
            self.reason = "未安装 langgraph/langchain-openai，运行于本地规则兜底模式"
            return
        try:
            self._llm = ChatOpenAI(
                model=model,
                api_key=api_key,
                base_url=base_url or None,
                temperature=0.2,
            )
        except Exception as exc:  # noqa: BLE001
            self.reason = f"Agent 初始化失败（{exc.__class__.__name__}: {exc}）"

    @property
    def available(self) -> bool:
        return self._llm is not None

    # ---------- specialist 选择：PROMPT + TOOLS + GRAPH ---------------------
    def _prompt_for(self, intent: str, lang: str) -> str:
        key = (intent, lang)
        cached = self._prompt_cache.get(key)
        if cached:
            return cached
        if lang == "ja":
            p = {
                "order": _ja_order_prompt(),
                "after_sales": _ja_after_sales_prompt(),
                "recommend": _ja_recommend_prompt(),
            }.get(intent) or _ja_generic_prompt()
        else:
            p = {
                "order": _zh_order_prompt(),
                "after_sales": _zh_after_sales_prompt(),
                "recommend": _zh_recommend_prompt(),
            }.get(intent) or _zh_generic_prompt()
        self._prompt_cache[key] = p
        return p

    def _tools_for(self, intent: str) -> list:
        if intent == "order":
            return [query_order_info, track_logistics]
        if intent == "after_sales":
            return [handle_return]
        if intent == "recommend":
            return [recommend_products]
        # chitchat / unknown / human -> 全量兜底
        return [query_order_info, track_logistics, handle_return, recommend_products]

    def _get_graph(self, intent: str, lang: str):
        if self._llm is None:
            return None
        key = (intent, lang)
        g = self._graphs.get(key)
        if g is not None:
            return g
        try:
            g = _build_react_agent(self._llm, self._tools_for(intent), self._prompt_for(intent, lang))
        except Exception as exc:  # noqa: BLE001
            self.reason = f"specialist({intent},{lang}) graph 构建失败（{exc.__class__.__name__}: {exc}）"
            g = None
        self._graphs[key] = g
        return g

    # ---------- 主入口：路由 + specialist 执行 --------------------------------
    def answer(self, question: str, history: list[dict] | None = None) -> dict | None:
        """Supervisor 路由调度，返回 {reply, intent, data}；失败返回 None（交由兜底）。"""
        q = question or ""
        intent, lang = _classify_by_regex(q)

        # 1. 人工接管：直接返回，不跑 LLM
        if intent == "human":
            return _build_human_reply(lang)

        # 2. 正则未命中 + LLM 可用 → LLM 精分
        if intent == "unknown" and self._llm is not None:
            refined = _classify_by_llm(q, lang, self._llm)
            if refined != "unknown":
                intent = refined

        # 3. 路由到 specialist graph
        graph = self._get_graph(intent, lang)
        if graph is None:
            return None  # 无 Key / 构建失败 → server 层走 classic_reply 兜底
        try:
            messages = [m for m in (history or []) if m.get("content")]
            messages.append({"role": "user", "content": q})
            result = graph.invoke({"messages": messages})
            formatted = self._format_result(result)
            # 回填 intent：tool 没检测到卡片时使用路由 intent
            if not formatted.get("intent") or formatted["intent"] in {"none", ""}:
                formatted["intent"] = intent
            return formatted
        except Exception:  # noqa: BLE001 - 网络/额度/格式异常都交给兜底
            return None

    # ---------- 内部：把 Agent 运行结果整理为结构化回复（与原版本一致） ----------
    @staticmethod
    def _format_result(result: dict) -> dict:
        msgs = result.get("messages") or []
        reply = ""
        intent, data = "none", None
        for m in reversed(msgs):
            if getattr(m, "content", ""):
                reply = m.content or ""
                break

        # 从本轮工具调用中还原"卡片信息"，让前端渲染订单 / 推荐卡片
        for m in msgs:
            calls = getattr(m, "tool_calls", None) or []
            for c in calls:
                name, args = c.get("name", ""), c.get("args") or {}
                if name == "recommend_products":
                    intent = "recommend"
                    data = {
                        "items": [
                            {"name": p["name"], "price": p["price"], "img": p["img"]}
                            for p in recommend_for(args.get("keywords") or [])
                        ]
                    }
                elif name in ("query_order_info", "track_logistics"):
                    order = lookup_order(args.get("order_no", ""))
                    if order:
                        intent = "order"
                        data = {
                            "order_no": order["order_no"],
                            "carrier": order["carrier"],
                            "paid_at": order["paid_at"],
                            "qty": order["qty"],
                            "total": order["total"],
                            "steps": order["steps"],
                            "product": {
                                "name": order["product"]["name"],
                                "price": order["product"]["price"],
                                "img": order["product"]["img"],
                            },
                        }
        return {"reply": reply, "intent": intent, "data": data}


# ============================================================================
# 3. 本地兜底路由：classic_reply（中文原分支一字未动 + 新增日语/人工分支）
# ============================================================================

def classic_reply(q: str) -> dict:
    """关键词路由 + 结构化卡片数据，返回 {reply, intent, data}。

    路由顺序：人工 → 语言判断 → 日语分支 or 中文分支（中文分支与改造前逐字相同）。
    """
    s = (q or "").lower()
    lang = _detect_lang(q or "")

    # --- 人工接管（中英日共用） ---
    if re.search(r"人工|真人|听不懂|转人|帮我接|找客服", s) or (
        lang == "ja" and re.search(r"オペレーター|人間|わかりません|繋いで|つないで", s)
    ):
        return _build_human_reply(lang)

    # --- 日语兜底分支 ---
    if lang == "ja":
        # 订单 / 物流
        if re.search(r"注文|配送|到着|追跡|発送|荷物|ちゅうもん|はいそう|单号|到哪|发货", s):
            order = lookup_order("2026081200012")
            if order:
                reply = (
                    f"ご注文 {order['order_no']} の現在位置は "
                    f"<span class='em'>「{order['location']}」</span> でございます。"
                    f"<br>到着予定は {order['eta']} ですので、今しばらくお待ちくださいませ。"
                    "配送拠点に到着しましたら SMS でもご案内いたします～"
                )
                return {"reply": reply, "intent": "order", "data": _order_card(order)}

        # 售后 / 退换
        if re.search(r"返品|交換|返金|不良|欠陥|修理|へんぴん|こうかん|退|换|退款|售后|质量|坏了", s):
            r = register_return("2026081200012", "品質不良")
            reply = (
                f"承知いたしました。この注文は「7日間無条件返品」期間内でございますので、"
                f"售后受付票 <span class='em'>{r['receipt']}</span> を発行いたしました。<br>"
                "ご希望の方法をお選びください：　① 返金のみ（元の決済手段へ）　"
                "② 新品交換（送料無料・優先発送）　③ 返品＆返金"
            )
            return {"reply": reply, "intent": "none", "data": None}

        # 推荐
        if re.search(r"おすすめ|人気|どれが|イヤホン|キーボード|水筒|モバイルバッテリー|推荐|什么好|哪款|耳机|键盘|保温杯|充电宝", s):
            items = recommend_for(["イヤホン", "キーボード", "モバイルバッテリー"])
            reply = (
                "ご要望に合わせまして、高く評価いただいている人気商品を 3 点ご案内いたします。"
                "<br>特に 1 点目のイヤホンはアクティブノイズキャンセリング搭載で、装着感も大変心地よくおすすめです～"
            )
            return {"reply": reply, "intent": "recommend", "data": {"items": _card_items(items)}}

        # 问候 / 闲聊
        if re.search(r"こんにちは|はじめまして|ありがとう|さようなら|すみません|ごめんなさい|在吗|你好|哈喽|hi|hello", s):
            return {
                "reply": "こんにちは～ ECCS AI カスタマーサポートでございます。"
                         "<br>注文確認・配送追跡・返品交換・商品のご案内ができます。"
                         "どうぞお気軽にご用件をお聞かせくださいませ～",
                "intent": "none",
                "data": None,
            }

        # 默认日语
        return {
            "reply": "承知いたしました。こちらのご質問につきまして対応させていただきます。<br>"
                     "例：<span class='em'>配送状況を確認したい / 返品したい / イヤホンのおすすめは？</span> など、お気軽にどうぞ。",
            "intent": "none",
            "data": None,
        }

    # --- 中文兜底分支（逐字保留原实现，100% 回归兼容） ---
    if re.search(r"物流|快递|到哪|发货|订单|单号|签收", s):
        order = lookup_order("2026081200012")
        p = order["product"]
        reply = (
            f"您的订单当前处于 <span class='em'>「{order['location']}」</span>，"
            f"预计{order['eta']}，到达派送点会有短信提醒～"
        )
        return {"reply": reply, "intent": "order", "data": _order_card(order)}

    if re.search(r"退|换|退款|售后|质量|坏了", s):
        r = register_return("2026081200012", "质量问题")
        reply = (
            f"可以的～该订单在 <span class='em'>7 天无理由</span> 期限内，"
            f"已为您登记售后单 <span class='em'>{r['receipt']}</span>。<br>"
            "① 仅退款（原路退回）　② 换新（免运费优先发）　③ 退货退款"
        )
        return {"reply": reply, "intent": "none", "data": None}

    if re.search(r"推荐|耳机|键盘|保温杯|充电宝|什么好|哪款", s):
        items = recommend_for(["耳机", "键盘", "充电宝"])
        reply = "根据您的需求推荐这 3 款高口碑好物，最推荐第一款，支持主动降噪、佩戴很舒适："
        return {"reply": reply, "intent": "recommend", "data": {"items": _card_items(items)}}

    if re.search(r"在吗|你好|哈喽|hi|hello|こんにちは", s):
        return {
            "reply": "您好呀～我是 ECCS 的 AI 智能客服，可以帮您查物流、办退换、挑商品，请直接告诉我需求即可～",
            "intent": "none",
            "data": None,
        }

    return {
        "reply": "收到～这个问题我可以处理。<br>您可以试试问我：<span class='em'>订单到哪了 / 怎么退货 / 推荐一款耳机</span>。",
        "intent": "none",
        "data": None,
    }


# ---- 卡片数据结构化（与 ui/app.js 的渲染约定保持一致）-------------------------
def _card_items(items: list[dict]) -> list[dict]:
    return [{"name": p["name"], "price": p["price"], "img": p["img"]} for p in items]


def _order_card(order: dict) -> dict:
    p = order["product"]
    return {
        "order_no": order["order_no"],
        "carrier": order["carrier"],
        "paid_at": order["paid_at"],
        "qty": order["qty"],
        "total": order["total"],
        "steps": order["steps"],
        "product": {"name": p["name"], "price": p["price"], "img": p["img"]},
    }
