# -*- coding: utf-8 -*-
"""认知层（core）：感知 / 思考 / 调度 / 反思 / 输出 五大模块的领地。

设计（见 docs/architecture.md）：
- core 管"怎么想、怎么调度"，agents/tools 管"做什么"，memory 管"记得什么"；
- 本包内各子包按需懒加载，不在此处导入重量级依赖。
"""