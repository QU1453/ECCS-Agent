# -*- coding: utf-8 -*-
"""约束层-验证层（ToolValidator）：工具调用的前置安全门，纯规则、零 token、微秒级。

主路径（任一道检查出问题即 block，错误提示返回给 agent）：
    收到工具请求 → 权限模式检查 → 文件路径检查 → 网络访问策略 → 危险内容/模式 → hook 规则 → 放行/拒绝 → 执行

权限模式四档（AGENT_PERMISSION_MODE，默认 plan）：
- plan：只读。写/执行类工具一律拦截（项目精度优先，逐步信任机制就绪后再放开）；
- ask：写类工具需人工确认，未接入确认通道前同样拦截（提示语不同）；
- accept：低风险写自动放行（仍要过路径/网络/危险检查）；
- bypass：完全放开（跳过全部检查，仅调试用）。

hook 规则（首条命中生效）：deny 优先于 allow 排布，如"允许 pytest、禁止 pip install"。
旁路容错：验证层自身异常时放行（不阻断主链路），由调用方 try/except 保证。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

from memory.access import MemoryCaller

import config

__all__ = ["ToolVerdict", "ToolValidator"]


# ---- 写/执行类工具命名兜底模式（除 config.TOOL_WRITE_TOOLS 显式名单外）----------------
_WRITE_NAME_RE = re.compile(
    r"(write|edit|delete|remove_|rm_|bash|shell|exec|install|pip|npm|yarn|curl|wget)",
    re.I,
)

# ---- 路径检查：敏感文件 / 穿越 -------------------------------------------------------
_SENSITIVE_RE = re.compile(
    r"(\.env(\.|$)|\.git(/|\\|$)|id_rsa|\.pem$|\.key$|\.sqlite3?$|\.ssh(/|\\|$))",
    re.I,
)
_PATH_KEYS = {"path", "file", "filepath", "file_path", "filename", "dir",
              "directory", "folder", "target", "output", "output_path", "cwd"}
_ABS_POSIX_RE = re.compile(r"^/")
_ABS_WIN_RE = re.compile(r"^[A-Za-z]:[\\/]")

# ---- 网络检查：URL 提取 + 云元数据端点（任何模式都禁）--------------------------------
_URL_RE = re.compile(r"(?:https?|ftp|wss?)://[^\s'\"<>]+", re.I)
_METADATA_HOSTS = {"169.254.169.254", "metadata.google.internal", "metadata.azure.com"}

# ---- 危险内容/危险模式（对全部字符串参数做子串正则扫描）-------------------------------
_DANGER_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("递归强删（rm -rf）", re.compile(r"\brm\s+(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r)\b", re.I)),
    ("提权执行（sudo/su）", re.compile(r"\b(sudo|su\s+root)\b", re.I)),
    ("fork 炸弹", re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}")),
    ("磁盘破坏（mkfs/dd）", re.compile(r"\bmkfs\b|\bdd\s+if=", re.I)),
    ("管道执行（| sh/bash）", re.compile(r"\|\s*(sh|bash|zsh|python3?|perl|powershell)\b", re.I)),
    ("下载执行（curl/wget）", re.compile(r"\b(curl|wget)\b", re.I)),
    ("全局权限修改（chmod 777）", re.compile(r"\bchmod\s+(-R\s+)?[0-7]{3,4}\s+/", re.I)),
    ("系统关机/重启", re.compile(r"\b(shutdown|reboot|halt|poweroff)\b", re.I)),
    ("读凭据文件", re.compile(r"/etc/(shadow|passwd)\b|\bcat\s+.*\.ssh/", re.I)),
    ("动态执行（eval/解码管道）", re.compile(r"\beval\b|\bbase64\s+(-d|--decode)\b", re.I)),
    ("依赖安装（pip/npm install）", re.compile(r"\b(pip3?|npm|yarn|pnpm)\s+install\b", re.I)),
    ("强制推送（git push -f）", re.compile(r"\bgit\s+push\b.*(--force|-f)\b", re.I)),
    ("毁坏性 SQL", re.compile(r"\bDROP\s+(TABLE|DATABASE)\b|\bTRUNCATE\s+TABLE\b", re.I)),
]

# ---- hook 默认规则（首条命中生效；deny 在前防"pip install pytest"被 allow 吞掉）--------
_DEFAULT_HOOKS: list[dict] = [
    # 用户例子：允许 pytest，禁止 pip install（依赖变更必须人工处理）
    {"name": r".*", "params": r"\bpip3?\s+install\b", "action": "deny",
     "reason": "禁止安装依赖（pip install）；如需新依赖请走人工流程"},
    {"name": r".*", "params": r"\bpytest\b|\bpython3?\s+-m\s+pytest\b", "action": "allow",
     "reason": "测试命令允许执行"},
    # 约束层自查工具的参数是被检文本（可能含危险串），放行避免误伤
    {"name": r"^(check_redline|sanitize_reply)$", "params": r".*", "action": "allow",
     "reason": "约束层自查工具：参数是待检查文本而非命令"},
]
_HOOKS: list[dict] = _DEFAULT_HOOKS + getattr(config, "TOOL_EXTRA_HOOKS", [])

_HOOK_NAME_RE: list[tuple[dict, re.Pattern, re.Pattern | None]] = []
for _h in _HOOKS:
    _hn = re.compile(_h.get("name", r".*"), re.I)
    _hp = re.compile(_h["params"]) if _h.get("params") else None
    _HOOK_NAME_RE.append((_h, _hn, _hp))


class ToolVerdict:
    """验证层结论：allowed=False 时 message 是返回给 agent 的错误提示。"""

    def __init__(self, allowed: bool, kind: str = "ok", message: str = ""):
        self.allowed = allowed
        self.kind = kind      # ok / permission / path / network / danger / hook
        self.message = message

    def __repr__(self) -> str:
        return f"ToolVerdict(allowed={self.allowed}, kind={self.kind!r})"


def _deny(kind: str, message: str) -> ToolVerdict:
    return ToolVerdict(False, kind, message)


class ToolValidator:
    """验证层：四道前置检查 + hook 规则，纯内存正则（无网络 / 无 LLM / 不耗 token）。"""

    name = "tool_validator"
    caller = MemoryCaller("tool_validator", "L3")

    # ---- 主入口：按主路径依次检查 ----------------------------------------------------
    def check(self, name: str, params: dict, caller: MemoryCaller | None = None) -> ToolVerdict:
        mode = str(config.AGENT_PERMISSION_MODE).lower()
        if mode == "bypass":
            return ToolVerdict(True)
        if _HOOK_NAME_RE:
            h = self._check_hooks(name, params)
            if h is not None:
                return h
        v = self._check_permission(name, mode)
        if not v.allowed:
            return v
        strings = list(_iter_strings(params))
        v = self._check_paths(params, strings)
        if not v.allowed:
            return v
        v = self._check_network(strings)
        if not v.allowed:
            return v
        return self._check_danger(strings)

    # ---- 1) 权限模式：plan 只读 / ask 待确认 / accept 低风险放行 ----------------------
    def _check_permission(self, name: str, mode: str) -> ToolVerdict:
        if not self._is_write(name):
            return ToolVerdict(True)
        if mode == "plan":
            return _deny("permission", (
                f"工具 {name} 属于写/执行类操作，当前权限模式为 plan（只读），已阻止执行。"
                "请改用只读工具收集信息后作答，或提示用户该操作暂未开放。"))
        if mode == "ask":
            return _deny("permission", (
                f"工具 {name} 属于写/执行类操作，ask 模式下需要人工确认后才能执行；"
                "确认通道尚未接入，本次调用已被阻止。"))
        return ToolVerdict(True)  # accept：低风险写放行，继续过后续检查

    @staticmethod
    def _is_write(name: str) -> bool:
        if name in config.TOOL_WRITE_TOOLS:
            return True
        return bool(_WRITE_NAME_RE.search(name or ""))

    # ---- 2) 文件路径检查：穿越 / 越界 / 敏感文件 --------------------------------------
    def _check_paths(self, params: dict, strings: list[str]) -> ToolVerdict:
        candidates = list(strings)
        for key, value in (params or {}).items():
            if str(key).lower() in _PATH_KEYS and isinstance(value, str):
                candidates.append(value)
        for text in candidates:
            body = _URL_RE.sub(" ", str(text))  # URL 归网络检查管辖，剥离后再查路径
            # 敏感文件对整个候选文本匹配（覆盖 ".env" 等无分隔符裸名，宁紧勿松）
            if _SENSITIVE_RE.search(body.replace("\\", "/")):
                return _deny("path", (
                    f"路径检查失败：'{str(text)[:60]}' 命中敏感文件（环境变量/密钥/数据库/.git）。"
                    "这类文件禁止读取或写入。"))
            for token in _path_tokens(body):
                if ".." in Path(token).parts:
                    return _deny("path", (
                        f"路径检查失败：'{token}' 包含 .. 目录穿越。"
                        "只允许访问项目目录内的文件。"))
                if token.startswith("~"):
                    return _deny("path", f"路径检查失败：'{token}' 指向用户主目录，超出允许范围。")
                if _ABS_POSIX_RE.match(token) or _ABS_WIN_RE.match(token):
                    if token in {"/", "//"}:
                        continue  # 裸根交给危险模式检查（如 rm -rf /），不算路径越界
                    real = os.path.realpath(os.path.expanduser(token))
                    roots = [os.path.realpath(os.path.expanduser(r)) for r in config.TOOL_PATH_ROOTS]
                    if not any(real == r or real.startswith(r + os.sep) or real.startswith(r + "/")
                               for r in roots):
                        return _deny("path", (
                            f"路径检查失败：'{token}' 越出允许的根目录（{config.TOOL_PATH_ROOTS}）。"
                            "禁止访问系统目录与项目外文件。"))
        return ToolVerdict(True)

    # ---- 3) 网络访问策略：deny / allowlist / allow，云元数据端点一律禁 ----------------
    def _check_network(self, strings: list[str]) -> ToolVerdict:
        policy = str(config.TOOL_NET_POLICY).lower()
        for text in strings:
            for url in _URL_RE.findall(text or ""):
                host = (urlparse(url).hostname or "").lower()
                if not host:
                    continue
                if host in _METADATA_HOSTS:
                    return _deny("network", (
                        f"网络访问被拒绝：{host} 是云主机元数据端点，任何模式下都禁止访问。"))
                if policy == "deny":
                    return _deny("network", (
                        f"网络访问被策略拒绝（policy=deny）：{url[:80]}。"
                        "当前环境禁止工具发起外部网络请求。"))
                if policy == "allowlist" and not self._host_allowed(host):
                    return _deny("network", (
                        f"网络访问被策略拒绝（policy=allowlist）：{host} 不在白名单。"
                        f"允许的域名：{config.TOOL_NET_ALLOW_HOSTS or '（空，全部禁止）'}。"))
        return ToolVerdict(True)

    @staticmethod
    def _host_allowed(host: str) -> bool:
        for h in config.TOOL_NET_ALLOW_HOSTS:
            if host == h or host.endswith("." + h):
                return True
        return False

    # ---- 4) 危险内容与危险模式 --------------------------------------------------------
    def _check_danger(self, strings: list[str]) -> ToolVerdict:
        for text in strings:
            for label, pattern in _DANGER_PATTERNS:
                m = pattern.search(text or "")
                if m:
                    return _deny("danger", (
                        f"危险操作被拦截：检测到「{label}」（片段：{m.group(0)[:40]}）。"
                        "如确有需要请由人工执行。"))
        return ToolVerdict(True)

    # ---- 5) hook 规则：首条命中生效，deny 拦截 / allow 放行并跳过后续检查 --------------
    @staticmethod
    def _check_hooks(name: str, params: dict) -> ToolVerdict | None:
        strings = list(_iter_strings(params))
        joined = "\n".join(strings)
        for hook, name_re, param_re in _HOOK_NAME_RE:
            if not name_re.search(name or ""):
                continue
            if param_re is not None and not param_re.search(joined):
                continue
            if hook.get("action") == "deny":
                return _deny("hook", (
                    f"工具调用被 hook 规则拦截：{hook.get('reason', '命中禁止规则')}。"))
            return ToolVerdict(True)  # allow：放行并跳过后续检查
        return None


# ---- 工具函数：递归取字符串 / 从文本中提取路径样 token --------------------------------
def _iter_strings(value, _depth: int = 0) -> list[str]:
    """递归展开参数里的全部字符串（dict/list/嵌套结构；防深度失控）。"""
    if _depth > 6:
        return []
    out: list[str] = []
    if isinstance(value, str):
        if value.strip():
            out.append(value)
    elif isinstance(value, dict):
        for k, v in value.items():
            out.extend(_iter_strings(k, _depth + 1))
            out.extend(_iter_strings(v, _depth + 1))
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            out.extend(_iter_strings(item, _depth + 1))
    return out


def _path_tokens(text: str) -> list[str]:
    """从一段文本中提取路径样 token（绝对路径 / ./ ../ ~/ 含分隔符片段）。"""
    tokens: list[str] = []
    for raw in re.findall(r"[^\s'\"，。；、！？:：()（）\[\]{}<>|]+", text or ""):
        if _ABS_POSIX_RE.match(raw) or _ABS_WIN_RE.match(raw) or raw.startswith("~"):
            tokens.append(raw)
        elif raw.startswith("./") or raw.startswith("../"):
            tokens.append(raw)
        elif "/" in raw or "\\" in raw:
            tokens.append(raw)
    return tokens
