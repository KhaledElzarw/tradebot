from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


SCHEMA_VERSION = "dashboard.snapshot.v1"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class StatusSnapshot(ContractModel):
    tsUtc: str | None = None
    symbol: str = "BTCUSDT"
    interval: str | None = None
    price: float | None = None
    equityUsdt: float | None = None
    usdt: float | None = None
    btc: float | None = None
    position: dict[str, Any] | None = None
    stats: dict[str, Any] = Field(default_factory=dict)


class RuntimeSnapshot(ContractModel):
    savedAt: str | None = None
    enginePid: int | None = None
    engineStartedAt: str | None = None
    market: dict[str, Any] = Field(default_factory=dict)
    grid: dict[str, Any] = Field(default_factory=dict)
    paper: dict[str, Any] = Field(default_factory=dict)
    stats: dict[str, Any] = Field(default_factory=dict)
    ai: dict[str, Any] | None = None


class CumulativeSnapshot(ContractModel):
    sinceUtc: str | None = None
    realizedPnlUsdt: float = 0.0
    grossRealizedPnlUsdt: float | None = None
    feesPaidUsdt: float = 0.0
    trades: int = 0
    wins: int = 0
    losses: int = 0


class EventSnapshot(ContractModel):
    tsUtc: str | None = None
    event: str | None = None
    symbol: str | None = None
    side: str | None = None
    price: float | None = None
    qtyBtc: float | None = None
    notionalUsdt: float | None = None


class OhlcvBar(ContractModel):
    openTimeMs: int
    open: float
    high: float
    low: float
    close: float
    volumeBase: float = 0.0
    closeTimeMs: int | None = None
    volumeUsdt: float = 0.0
    symbol: str = "BTCUSDT"
    interval: str


class EventPatch(ContractModel):
    mode: Literal["snapshot", "delta"]
    cursor: int = 0
    items: list[EventSnapshot] = Field(default_factory=list)


class OrderPatchOperation(ContractModel):
    op: Literal["upsert", "remove"]
    key: str
    item: dict[str, Any] | None = None


class OrderPatch(ContractModel):
    mode: Literal["snapshot", "delta"]
    signature: str = ""
    items: list[dict[str, Any]] = Field(default_factory=list)
    ops: list[OrderPatchOperation] = Field(default_factory=list)


class SnapshotEnvelope(ContractModel):
    schemaVersion: str = SCHEMA_VERSION
    serverInstanceId: str | None = None
    channel: Literal["dashboard", "status", "chart"]
    seq: int
    serverTimeUtc: str


class MarketStatusPayload(SnapshotEnvelope):
    channel: Literal["status"] = "status"
    status: StatusSnapshot
    state: dict[str, Any] = Field(default_factory=dict)
    runtime: RuntimeSnapshot
    cumulative: CumulativeSnapshot
    events: list[EventSnapshot] = Field(default_factory=list)
    eventsPatch: EventPatch | None = None
    ordersPatch: OrderPatch | None = None
    ohlcv: list[OhlcvBar] = Field(default_factory=list)
    chartInterval: str
    chartLimit: int
    chartOffset: int
    supportedIntervals: list[str] = Field(default_factory=list)
    freshnessSeconds: float | None = None
    refreshMs: int


class DashboardPayload(MarketStatusPayload):
    channel: Literal["dashboard"] = "dashboard"
    history: dict[str, Any] = Field(default_factory=dict)
    intelligence: dict[str, Any] = Field(default_factory=dict)
    aiEndpoints: list[dict[str, Any]] = Field(default_factory=list)
    aiEndpointKey: str | None = None
    aiEndpointLabel: str | None = None
    aiEndpointModels: dict[str, list[str]] = Field(default_factory=dict)
    aiModels: list[str] = Field(default_factory=list)
    dashboardRefreshMs: int


class ChartTickPayload(SnapshotEnvelope):
    channel: Literal["chart"] = "chart"
    chartInterval: str
    bar: OhlcvBar | None = None
    status: StatusSnapshot | None = None
    freshnessSeconds: float | None = None
    refreshMs: int


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_market_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return MarketStatusPayload.model_validate(payload).model_dump(mode="json", exclude_none=True)


def validate_dashboard_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return DashboardPayload.model_validate(payload).model_dump(mode="json", exclude_none=True)


def validate_chart_tick_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return ChartTickPayload.model_validate(payload).model_dump(mode="json", exclude_none=True)
