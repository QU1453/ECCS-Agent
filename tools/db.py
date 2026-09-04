# -*- coding: utf-8 -*-
"""SQLite 数据源：商品 / 订单 / 售后单的建表、连接与演示数据播种。

- 库文件：data/shop.db（已被 .gitignore 拦截，不入库）；
- 首次运行自动建表并播种演示数据（与原硬编码数据一致，老演示不受影响）；
- 每次调用独立连接（uvicorn 并发安全），开启 WAL 提升读写并发；
- 录单 / 推进物流 / 加商品等维护操作见项目根目录 admin.py。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "shop.db"

# 订单状态 → 轨迹展示的固定流转（真实版替换为物流 API 回调节点）
STATUS_FLOW = ["paid", "transporting", "delivering", "done"]
STATUS_TEXT = {"unpaid": "未付款", "paid": "已付款", "transporting": "运输中", "delivering": "派送中", "done": "已签收"}
# 每个状态对应的当前位置 / 预计送达（演示口径，真实版来自物流 API）
STATUS_SCENE = {
    "paid": ("卖家已打包", "预计 48 小时内发货"),
    "transporting": ("广州转运中心", "明天 18:00 前送达"),
    "delivering": ("上海浦东派送点", "今日 21:00 前送达"),
    "done": ("已签收", "已送达"),
}


def get_conn() -> sqlite3.Connection:
    """独立连接（并发安全）；行转 dict；确保库目录存在。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """建表 + 空库时播种演示数据（幂等：表存在则跳过）。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                code     TEXT PRIMARY KEY,         -- 商品编码（订单外键引用）
                name     TEXT NOT NULL,            -- 商品名
                price    REAL NOT NULL,            -- 价格（元）
                img      TEXT NOT NULL,            -- 商品图 URL
                feature  TEXT NOT NULL,            -- 卖点（推荐理由来源）
                category TEXT NOT NULL DEFAULT 'general'  -- 品类（推荐按类命中，如 book/audio）
            );
            CREATE TABLE IF NOT EXISTS orders (
                order_no     TEXT PRIMARY KEY,     -- 订单号（YYYYMMDD+5位序号）
                product_code TEXT NOT NULL REFERENCES products(code),
                qty          INTEGER NOT NULL,
                total        REAL NOT NULL,
                paid_at      TEXT NOT NULL,        -- 付款时间（展示文案）
                status       TEXT NOT NULL,        -- paid/transporting/delivering/done
                carrier      TEXT NOT NULL,        -- 承运商
                created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS after_sales (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,  -- 售后单号 #SA-{id+2032}
                order_no     TEXT NOT NULL,
                reason       TEXT NOT NULL,
                created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            );
            """
        )
        # 老库升级：补 category 列（已存在则忽略），并给品类为空的商品按编码补齐
        try:
            conn.execute("ALTER TABLE products ADD COLUMN category TEXT NOT NULL DEFAULT 'general'")
        except sqlite3.OperationalError:
            pass  # 列已存在
        conn.execute("UPDATE products SET category = code WHERE category = 'general'")
        _seed_if_empty(conn)
        conn.commit()
    finally:
        conn.close()


def _seed_if_empty(conn: sqlite3.Connection) -> None:
    """空表时写入与原演示数据一致的商品 / 订单，保证老演示口径不变。"""
    if conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"] == 0:
        # category 即品类编码：book=图书 / audio=耳机 / keyboard=键盘 / tumbler=保温杯 / power=充电宝
        conn.executemany(
            "INSERT INTO products(code, name, price, img, feature, category) VALUES(?,?,?,?,?,?)",
            [
                ("earbuds", "云感无线蓝牙耳机 Pro · 半入耳", 299,
                 "https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=studio%20product%20photo%20minimalist%20white%20wireless%20earbuds%20open%20charging%20case%20soft%20warm%20beige%20background&image_size=square",
                 "主动降噪、佩戴舒适、续航 36 小时", "audio"),
                ("keyboard", "奶糖机械键盘 87 键 · 奶油橙", 459,
                 "https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=studio%20product%20photo%20retro%20cream%20mechanical%20keyboard%20warm%20orange%20keycaps%20soft%20beige%20background&image_size=square",
                 "奶油轴手感软弹、三模连接、支持 Windows/Mac", "keyboard"),
                ("tumbler", "山雾保温杯 450ml · 燕麦奶", 129,
                 "https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=studio%20product%20photo%20cream%20matte%20insulated%20tumbler%20with%20lid%20warm%20beige%20background&image_size=square",
                 "316 不锈钢、保温 12h / 保冷 24h", "tumbler"),
                ("power", "珊瑚移动电源 10000mAh · 快充", 189,
                 "https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=studio%20product%20photo%20slim%20coral%20orange%20power%20bank%20warm%20neutral%20background&image_size=square",
                 "22.5W 快充、双口输出、可上飞机", "power"),
            ],
        )
    if conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"] == 0:
        # 演示主订单：与 ui/app.js、classic_reply 兜底引用的订单号保持一致
        conn.execute(
            "INSERT INTO orders(order_no, product_code, qty, total, paid_at, status, carrier)"
            " VALUES('2026081200012', 'earbuds', 1, 299, '昨天 15:02 付款', 'transporting', '顺丰速运')"
        )


def order_steps(status: str) -> list[dict]:
    """按当前状态生成四段轨迹（done=已完成 / cur=进行中 / 空=未到）；未付款时全部未到。"""
    if status == "unpaid":
        return [{"label": STATUS_TEXT[st], "state": ""} for st in STATUS_FLOW]
    idx = STATUS_FLOW.index(status) if status in STATUS_FLOW else 0
    return [
        {"label": STATUS_TEXT[st], "state": "done" if i < idx else ("cur" if i == idx else "")}
        for i, st in enumerate(STATUS_FLOW)
    ]


# 启动即初始化（幂等）：server / admin / 任意入口 import tools 时自动就绪
init_db()
