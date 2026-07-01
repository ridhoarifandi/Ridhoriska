"""Klien data TradingView.

Dua backend di balik antarmuka yang sama:
  - "mcp"    : spawn local MCP bridge (bidouilles/mcp-tradingview-server) via stdio,
               panggil tool get_indicators. -> sesuai permintaan "local mcp bridge".
  - "direct" : pakai library tradingview_scraper langsung di proses ini (fallback).

Keduanya mengembalikan snapshot indikator TradingView (RSI, MACD, EMA, ATR,
Recommend.All, dst) per (symbol, timeframe).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any


# --------------------------------------------------------------------------- #
# Backend: MCP bridge (stdio)
# --------------------------------------------------------------------------- #
async def _mcp_fetch_all(bridge: dict, jobs: list[tuple[str, str, str]]) -> dict:
    """Buka satu sesi MCP, ambil indikator untuk semua (symbol, exchange, tf)."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=bridge["command"],
        args=bridge.get("args", []),
        cwd=bridge.get("cwd"),
    )

    out: dict = {}
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for symbol, exchange, tf in jobs:
                try:
                    res = await session.call_tool(
                        "get_indicators",
                        {
                            "symbol": symbol,
                            "exchange": exchange,
                            "timeframe": tf,
                            "all_indicators": True,
                        },
                    )
                    out[(symbol, tf)] = _parse_tool_result(res)
                except Exception as e:  # noqa: BLE001
                    out[(symbol, tf)] = {"_error": f"{type(e).__name__}: {e}"}
    return out


def _parse_tool_result(res: Any) -> dict:
    """Ekstrak dict 'indicators' dari hasil tool MCP (yang berupa konten teks JSON)."""
    payload = None
    content = getattr(res, "content", None)
    if content:
        for block in content:
            text = getattr(block, "text", None)
            if text:
                try:
                    payload = json.loads(text)
                    break
                except json.JSONDecodeError:
                    continue
    if payload is None:
        sc = getattr(res, "structuredContent", None)
        if isinstance(sc, dict):
            payload = sc
    if not isinstance(payload, dict):
        return {"_error": "respons tool tidak bisa diparse"}
    return _unwrap_indicators(payload)


def _unwrap_indicators(node: Any, depth: int = 0) -> dict:
    """Turun melewati pembungkus {indicators|data: {...}} sampai ketemu dict indikator asli.

    Bentuk MCP bidouilles: {success, ..., indicators: {status, data: {RSI, ...}}}.
    """
    if not isinstance(node, dict):
        return {"_error": "format indikator tak dikenal"}
    if "Recommend.All" in node or "RSI" in node or "close" in node:
        return node
    if depth < 5:
        for key in ("indicators", "data"):
            if isinstance(node.get(key), dict):
                return _unwrap_indicators(node[key], depth + 1)
    return node


# --------------------------------------------------------------------------- #
# Backend: direct (tradingview_scraper)
# --------------------------------------------------------------------------- #
def _direct_fetch_all(jobs: list[tuple[str, str, str]]) -> dict:
    from tradingview_scraper.symbols.technicals import Indicators

    scraper = Indicators(export_result=False)
    out: dict = {}
    for symbol, exchange, tf in jobs:
        try:
            res = scraper.scrape(
                exchange=exchange,
                symbol=symbol,
                timeframe=tf,
                allIndicators=True,
            )
            if isinstance(res, dict) and (res.get("indicators") or res.get("data")):
                out[(symbol, tf)] = res.get("indicators") or res.get("data")
            elif isinstance(res, dict):
                out[(symbol, tf)] = res
            else:
                out[(symbol, tf)] = {"_error": "format tak dikenal"}
        except Exception as e:  # noqa: BLE001
            out[(symbol, tf)] = {"_error": f"{type(e).__name__}: {e}"}
    return out


# --------------------------------------------------------------------------- #
# API publik
# --------------------------------------------------------------------------- #
def fetch_indicators(cfg: dict) -> dict:
    """Ambil snapshot indikator untuk semua symbol x timeframe di config.

    Return: { (symbol, timeframe): {field: value, ...}, ... }
    """
    timeframes = cfg["timeframes"]
    jobs: list[tuple[str, str, str]] = []
    for s in cfg["symbols"]:
        for tf in timeframes:
            jobs.append((s["symbol"], s["exchange"], tf))

    backend = cfg.get("data_backend", "mcp")
    if backend == "mcp":
        return asyncio.run(_mcp_fetch_all(cfg["bridge"], jobs))
    elif backend == "direct":
        return _direct_fetch_all(jobs)
    raise ValueError(f"data_backend tidak dikenal: {backend}")
