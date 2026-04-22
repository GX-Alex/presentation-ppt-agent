"""
协作式取消令牌 — 用于 Deck→Page→Lane 级联取消传播。

借鉴 deer-flow 的 cooperative cancellation 设计:
- 父级取消时，所有子级自动收到取消信号
- 子级可通过 check() 或 await wait() 检查取消状态
- 支持超时自动取消（per-lane 超时）

使用方式:
    # Deck 级别创建根令牌
    deck_token = CancellationToken()

    # Page 级别派生子令牌（带超时）
    page_token = deck_token.child(timeout=120.0)

    # Lane 级别派生子令牌
    lane_token = page_token.child(timeout=60.0)

    # 在异步操作中检查取消
    if lane_token.is_cancelled:
        raise CooperativeCancelledError("lane cancelled")

    # 或等待取消事件
    await lane_token.wait(timeout=5.0)
"""
import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class CooperativeCancelledError(Exception):
    """协作式取消操作引发的异常。
    命名为 CooperativeCancelledError 以避免与 asyncio.CancelledError 混淆。
    """

    def __init__(self, reason: str = "operation cancelled"):
        self.reason = reason
        super().__init__(reason)


class CancellationToken:
    """协作式取消令牌，支持父子级联和超时自动取消。"""

    def __init__(
        self,
        *,
        parent: "CancellationToken | None" = None,
        timeout: float | None = None,
        label: str = "",
    ) -> None:
        self._cancelled = False
        self._event = asyncio.Event()
        self._parent = parent
        self._children: list["CancellationToken"] = []
        self._label = label
        self._timeout = timeout
        self._timeout_handle: asyncio.TimerHandle | None = None
        self._cancel_reason: str = ""

        # 如果父令牌已取消，子令牌也立即取消
        if parent is not None:
            parent._children.append(self)
            if parent.is_cancelled:
                self._do_cancel(f"父级已取消: {parent._cancel_reason}")

        # 设置超时自动取消
        if timeout is not None and timeout > 0 and not self._cancelled:
            try:
                loop = asyncio.get_running_loop()
                self._timeout_handle = loop.call_later(
                    timeout,
                    self._on_timeout,
                )
            except RuntimeError:
                # 不在事件循环中——跳过超时设置
                pass

    @property
    def is_cancelled(self) -> bool:
        """检查令牌是否已取消（含父级传播检查）。"""
        if self._cancelled:
            return True
        if self._parent is not None and self._parent.is_cancelled:
            self._do_cancel(f"父级已取消: {self._parent._cancel_reason}")
            return True
        return False

    @property
    def cancel_reason(self) -> str:
        return self._cancel_reason

    @property
    def label(self) -> str:
        return self._label

    def cancel(self, reason: str = "manual cancel") -> None:
        """主动取消令牌，级联取消所有子令牌。"""
        self._do_cancel(reason)

    def _do_cancel(self, reason: str) -> None:
        """内部取消实现——设置标志 + 通知事件 + 级联子令牌。"""
        if self._cancelled:
            return
        self._cancelled = True
        self._cancel_reason = reason
        self._event.set()

        # 清除超时定时器
        if self._timeout_handle is not None:
            self._timeout_handle.cancel()
            self._timeout_handle = None

        # 级联取消所有子令牌
        for child in self._children:
            child._do_cancel(f"父级取消: {reason}")

        label_info = f" [{self._label}]" if self._label else ""
        logger.info(f"[Cancellation] 令牌已取消{label_info}: {reason}")

    def _on_timeout(self) -> None:
        """超时回调——自动取消。"""
        self._timeout_handle = None
        timeout_str = f"{self._timeout:.0f}s" if self._timeout else "unknown"
        self._do_cancel(f"超时 ({timeout_str})")

    def child(
        self,
        *,
        timeout: float | None = None,
        label: str = "",
    ) -> "CancellationToken":
        """创建子令牌，继承父级取消状态。"""
        return CancellationToken(parent=self, timeout=timeout, label=label)

    async def wait(self, timeout: float | None = None) -> bool:
        """等待取消事件。

        Returns:
            True 表示已取消; False 表示超时仍未取消
        """
        if self.is_cancelled:
            return True
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def check(self) -> None:
        """检查取消状态，已取消则抛出 CooperativeCancelledError。"""
        if self.is_cancelled:
            raise CooperativeCancelledError(self._cancel_reason)

    def cleanup(self) -> None:
        """清理资源——取消超时定时器，断开父子关系。"""
        if self._timeout_handle is not None:
            self._timeout_handle.cancel()
            self._timeout_handle = None
        if self._parent is not None:
            try:
                self._parent._children.remove(self)
            except ValueError:
                pass
        for child in self._children:
            child.cleanup()
        self._children.clear()

    def __repr__(self) -> str:
        status = "cancelled" if self._cancelled else "active"
        label = f" {self._label}" if self._label else ""
        return f"<CancellationToken{label} {status}>"
