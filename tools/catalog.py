# -*- coding: utf-8 -*-
"""商品演示库：商品资料 + 关键词推荐匹配（真实上线时替换为商品库 / RAG 检索）。"""
from __future__ import annotations

from urllib.parse import quote

_IMG_TEMPLATE = "https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt={prompt}&image_size=square"


def _img(raw_prompt: str) -> str:
    """商品演示图 URL（按提示词生成的占位图；真实版换商品库图片地址）。"""
    return _IMG_TEMPLATE.format(prompt=quote(raw_prompt))


# 演示商品库：code → {code, name, price, img, feature}，真实版对接商品中心 API
PRODUCTS = {
    "earbuds": {
        "code": "earbuds",
        "name": "云感无线蓝牙耳机 Pro · 半入耳",
        "price": 299,
        "img": _img("studio product photo minimalist white wireless earbuds open charging case soft warm beige background"),
        "feature": "主动降噪、佩戴舒适、续航 36 小时",
    },
    "keyboard": {
        "code": "keyboard",
        "name": "奶糖机械键盘 87 键 · 奶油橙",
        "price": 459,
        "img": _img("studio product photo retro cream mechanical keyboard warm orange keycaps soft beige background"),
        "feature": "奶油轴手感软弹、三模连接、支持 Windows/Mac",
    },
    "tumbler": {
        "code": "tumbler",
        "name": "山雾保温杯 450ml · 燕麦奶",
        "price": 129,
        "img": _img("studio product photo cream matte insulated tumbler with lid warm beige background"),
        "feature": "316 不锈钢、保温 12h / 保冷 24h",
    },
    "power": {
        "code": "power",
        "name": "珊瑚移动电源 10000mAh · 快充",
        "price": 189,
        "img": _img("studio product photo slim coral orange power bank warm neutral background"),
        "feature": "22.5W 快充、双口输出、可上飞机",
    },
}
