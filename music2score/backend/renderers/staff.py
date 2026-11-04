"""五线谱渲染：MusicXML -> Verovio -> SVG。

Verovio 的资源（字体）初始化是线程本地的：哪个线程第一次渲染，之后只有那个
线程能正常加载字体，其他线程 loadData 会静默失败。所以所有渲染都固定提交到
一个专用单线程池里执行（见 _render_in_worker）。
"""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from ..models import Score
from .musicxml import build_musicxml

VEROVIO_OPTIONS = {
    "adjustPageHeight": True,
    "pageWidth": 1760,
    "pageHeight": 1000,
    "pageMarginLeft": 42,
    "pageMarginRight": 42,
    "pageMarginTop": 26,
    "pageMarginBottom": 26,
    "svgViewBox": True,
    "footer": "none",
    "header": "none",
    "breaks": "auto",
    "systemMaxPerPage": 8,
    "spacingStaff": 10,
    "spacingSystem": 14,
    "scale": 100,
    "font": "Bravura",
}

_POOL: ThreadPoolExecutor | None = None
_POOL_LOCK = Lock()


def _render_pool() -> ThreadPoolExecutor:
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="verovio")
        return _POOL


def _render_pages_sync(xml: str) -> list:
    import verovio

    tk = verovio.toolkit()
    try:
        tk.setOptions(VEROVIO_OPTIONS)
    except TypeError:
        tk.setOptions(json.dumps(VEROVIO_OPTIONS))
    if not tk.loadData(xml):
        res = ""
        try:
            res = tk.getResourcePath()
        except Exception:
            pass
        raise RuntimeError(f"Verovio 无法解析生成的 MusicXML（资源路径 {res}）")
    pages = tk.getPageCount() or 1
    return [tk.renderToSVG(i + 1) for i in range(pages)]


def _render_in_worker(xml: str, timeout: float = 180.0) -> list:
    future = _render_pool().submit(_render_pages_sync, xml)
    return future.result(timeout=timeout)


def render_staff_svg(score: Score, title: str = None) -> str:
    xml = build_musicxml(score, title)
    return "\n".join(_render_in_worker(xml))


def render_staff_pages(score: Score, title: str = None) -> list:
    """返回分页 SVG 列表，便于前端逐页排版。"""
    xml = build_musicxml(score, title)
    return _render_in_worker(xml)
