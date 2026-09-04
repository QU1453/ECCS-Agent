# -*- coding: utf-8 -*-
"""ECCS 现场录单工具（admin.py）：答辩演示「现场下单、现场查」的运维入口。

数据落在 data/shop.db（SQLite），agent 实时查库——录完单立刻可以问客服。

常用命令：
    python admin.py list                       # 查看全部订单
    python admin.py add earbuds 1              # 录单：1 个耳机，自动生成订单号
    python admin.py advance 2026090400001      # 推进物流（付款→运输→派送→签收）
    python admin.py add-product book 79 "《跨境电商实战》" "日本市场选品与合规"  # 加商品
    python admin.py products                   # 查看商品库
    python admin.py reset                      # 清空并重置为演示数据（慎用）
"""
from __future__ import annotations

import sys
from urllib.parse import quote

from tools import advance_order, create_order, list_orders, lookup_order
from tools.catalog import get_products
from tools.db import STATUS_TEXT, init_db

_IMG = "https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt={p}&image_size=square"


def _img(prompt: str) -> str:
    """按商品名生成演示图（真实版改为上传图床 / 商品中心图片 URL）。"""
    return _IMG.format(p=quote(prompt))


def cmd_list() -> None:
    """打印全部订单（含状态中文），最新在前。"""
    orders = list_orders()
    if not orders:
        print("（暂无订单）")
        return
    print(f"共 {len(orders)} 单：")
    for o in orders:
        status = STATUS_TEXT.get(o["status"], o["status"])
        print(f"  {o['order_no']}  {status:　<4} {o['product_code']} x{o['qty']}  ¥{o['total']}  {o['paid_at']}")


def cmd_add(product_code: str, qty: int) -> None:
    """录单：校验商品存在 → create_order → 打印订单号与信息。"""
    try:
        order = create_order(product_code, qty=qty)
    except ValueError as exc:
        print(f"录单失败：{exc}")
        print(f"当前可用商品编码：{', '.join(get_products())}")
        return
    print(f"录单成功！订单号：{order['order_no']}（{order['product']['name']} x{qty} = ¥{order['total']}）")
    print("现在可以直接问客服：「订单 {} 到哪了？」".format(order["order_no"]))


def cmd_advance(order_no: str) -> None:
    """推进物流状态一步，并展示最新轨迹。"""
    order = advance_order(order_no)
    if order is None:
        print(f"未找到订单 {order_no}")
        return
    track = " → ".join(f"{s['label']}{'✓' if s['state'] == 'done' else ('•' if s['state'] == 'cur' else '')}"
                       for s in order["steps"])
    print(f"订单 {order['order_no']} 已推进：{track}")
    print(f"当前位置：{order['location']}　{order['eta']}")


def cmd_add_product(code: str, price: float, name: str, feature: str, category: str = "general") -> None:
    """加商品：录完立刻可被推荐与下单（category 用于按品类推荐，如 book/audio）。"""
    from tools.db import get_conn

    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO products(code, name, price, img, feature, category)"
            " VALUES(?,?,?,?,?,?)",
            (code.strip(), name, price,
             _img(f"studio product photo {name} warm beige background"), feature, category.strip()),
        )
        conn.commit()
    finally:
        conn.close()
    print(f"商品已上架：{code}（{name} ¥{price}，品类 {category}）——现在问客服「推荐一下」就能看到它")


def cmd_products() -> None:
    """打印商品库。"""
    for code, p in get_products().items():
        print(f"  {code:<10} ¥{p['price']:<8} {p['name']}　卖点：{p['feature']}")


def cmd_reset() -> None:
    """清库重建（恢复演示数据）。"""
    from tools.db import DB_PATH

    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()
    print(f"已重置为演示数据：{DB_PATH}")


def main(argv: list[str]) -> None:
    init_db()  # 幂等：首次运行自动建表播种
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    cmd, *args = argv
    if cmd == "list":
        cmd_list()
    elif cmd == "add" and len(args) >= 1:
        cmd_add(args[0], int(args[1]) if len(args) > 1 else 1)
    elif cmd == "advance" and args:
        cmd_advance(args[0])
    elif cmd == "add-product" and len(args) >= 4:
        cmd_add_product(args[0], float(args[1]), args[2], args[3], args[4] if len(args) > 4 else "general")
    elif cmd == "products":
        cmd_products()
    elif cmd == "reset":
        cmd_reset()
    else:
        print("命令不识别，用法如下：")
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
