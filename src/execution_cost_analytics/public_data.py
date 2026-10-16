"""Archives publiques Binance Vision : téléchargement vérifié et provenance explicite.

Les séries de prix utilisent le VWAP de transactions des barres, pas le milieu
d'une fourchette bid/ask. Le spread et l'impact restent des hypothèses du modèle.
"""

import calendar
import hashlib
import io
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen
from zipfile import ZipFile

import numpy as np
import pandas as pd

DATA_LICENSE = "CC BY-NC-SA 4.0 (Binance Vision Dataset Terms)"
TERMS_URL = "https://github.com/binance/binance-public-data/blob/master/TERMS_AND_CONDITIONS.md"
SOURCE_URL = "https://github.com/binance/binance-public-data"
MODEL_UNIT = 1e-6
KLINE_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trades",
    "taker_base",
    "taker_quote",
    "ignore",
]


def _validate_request(symbol: str, month: str) -> None:
    if not re.fullmatch(r"[A-Z0-9]{5,20}", symbol):
        raise ValueError("Le symbole doit être un identifiant alphanumérique majuscule.")
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("month doit respecter YYYY-MM.")
    datetime.strptime(month, "%Y-%m")


def archive_to_market(
    payload: bytes,
    symbol: str,
    month: str,
    spread_bps: float = 2.0,
) -> tuple[pd.DataFrame, dict]:
    """Valider une archive mensuelle 1 min, puis agréger en 48 barres par jour UTC.

    Les quantités entières représentent des millionièmes d'actif. Cette unité
    sert au calcul et n'est pas présentée comme un pas de cotation du marché.
    """
    _validate_request(symbol, month)
    if not np.isfinite(spread_bps) or spread_bps < 0:
        raise ValueError("spread_bps doit être fini et non négatif.")
    expected_name = f"{symbol}-1m-{month}.csv"
    with ZipFile(io.BytesIO(payload)) as archive:
        if archive.namelist() != [expected_name]:
            raise ValueError("L'archive doit contenir uniquement le CSV mensuel attendu.")
        info = archive.getinfo(expected_name)
        if info.file_size > 100_000_000:
            raise ValueError("Archive décompressée trop volumineuse pour ce protocole.")
        with archive.open(info) as source:
            raw = pd.read_csv(source, header=None, names=KLINE_COLUMNS)
    for column in KLINE_COLUMNS[:-1]:
        raw[column] = pd.to_numeric(raw[column], errors="raise")
    values = raw[KLINE_COLUMNS[:-1]].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("Valeurs non finies dans l'archive de marché.")
    if (raw[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("Les prix des barres doivent être positifs.")
    if (raw[["volume", "quote_volume", "trades"]] < 0).any().any():
        raise ValueError("Volumes et nombre de transactions doivent être non négatifs.")
    if (
        (raw["high"] < raw[["open", "close", "low"]].max(axis=1))
        | (raw["low"] > raw[["open", "close", "high"]].min(axis=1))
    ).any():
        raise ValueError("Barres OHLC incohérentes.")
    if ((raw["volume"] == 0) & (raw["quote_volume"] != 0)).any():
        raise ValueError("Volume nul avec notionnel non nul.")
    active = raw["volume"] > 0
    trade_vwap = raw.loc[active, "quote_volume"] / raw.loc[active, "volume"]
    tolerance = np.maximum(1e-8, raw.loc[active, "high"] * 1e-8)
    if (
        (trade_vwap <= 0)
        | (trade_vwap < raw.loc[active, "low"] - tolerance)
        | (trade_vwap > raw.loc[active, "high"] + tolerance)
    ).any():
        raise ValueError("Le VWAP de transactions doit être positif et cohérent avec OHLC.")
    # Le producteur utilise les microsecondes depuis janvier 2025.
    unit = "us" if raw["open_time"].max() > 100_000_000_000_000 else "ms"
    raw["timestamp"] = pd.to_datetime(raw["open_time"], unit=unit, utc=True).dt.tz_localize(None)
    start = pd.Timestamp(month + "-01")
    stop = start + pd.offsets.MonthBegin(1)
    expected = pd.date_range(start, stop, freq="min", inclusive="left")
    if not pd.DatetimeIndex(raw["timestamp"]).equals(expected):
        raise ValueError("Archive incomplète, dupliquée, non triée ou hors du mois demandé.")
    raw["bar"] = raw["timestamp"].dt.floor("30min")
    bars = (
        raw.groupby("bar", sort=True)
        .agg(
            base_volume=("volume", "sum"),
            quote_volume=("quote_volume", "sum"),
            first_open=("open", "first"),
            last_close=("close", "last"),
            minutes=("timestamp", "count"),
        )
        .reset_index()
    )
    if not bars["minutes"].eq(30).all():
        raise ValueError("Chaque barre doit contenir exactement 30 minutes observées.")
    vwap = np.divide(
        bars["quote_volume"].to_numpy(),
        bars["base_volume"].to_numpy(),
        out=bars["last_close"].to_numpy(copy=True),
        where=bars["base_volume"].to_numpy() > 0,
    )
    units = np.floor(bars["base_volume"].to_numpy() / MODEL_UNIT)
    if (units > np.iinfo(np.int64).max).any():
        raise ValueError("Le volume dépasse la capacité de l'unité de calcul.")
    market = pd.DataFrame(
        {
            "timestamp": bars["bar"],
            "session": bars["bar"].dt.strftime("%Y-%m-%d"),
            "bucket": bars["bar"].dt.hour * 2 + bars["bar"].dt.minute // 30,
            "mid_price": vwap * MODEL_UNIT,
            "market_volume": units.astype(np.int64),
            "spread_bps": spread_bps,
            "open_price": bars["first_open"].to_numpy() * MODEL_UNIT,
            "close_price": bars["last_close"].to_numpy() * MODEL_UNIT,
        }
    )
    quality = {
        "symbol": symbol,
        "month": month,
        "raw_minutes": len(raw),
        "expected_minutes": calendar.monthrange(start.year, start.month)[1] * 1440,
        "sessions": int(market["session"].nunique()),
        "bars_per_session": 48,
        "missing_minutes": 0,
        "duplicate_minutes": 0,
        "zero_volume_bars": int((units == 0).sum()),
        "timestamp_unit": unit,
        "timezone": "UTC",
        "price_proxy": "bar_trade_vwap_quote_volume_divided_by_base_volume_not_bid_ask_mid",
        "spread_bps_assumed": spread_bps,
        "model_asset_unit": MODEL_UNIT,
        "lot_size_claim": "model_unit_only_not_exchange_trading_filter",
        "zero_volume_price": "last_close_reference_only_no_execution",
    }
    return market, quality


def _download(url: str, maximum_bytes: int) -> bytes:
    request = Request(
        url, headers={"User-Agent": "execution-cost-analytics/0.2 educational research"}
    )
    with urlopen(request, timeout=60) as response:
        payload = response.read(maximum_bytes + 1)
    if len(payload) > maximum_bytes:
        raise ValueError("La réponse dépasse la taille maximale attendue.")
    return payload


def fetch_public_data(
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT"),
    month: str = "2026-01",
    output_dir: str | Path = "data/public",
) -> list[Path]:
    """Télécharger deux fichiers par actif, vérifier SHA-256, conserver les bruts localement."""
    if not symbols or len(set(symbols)) != len(symbols):
        raise ValueError("Une liste de symboles distincts est requise.")
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for symbol in symbols:
        _validate_request(symbol, month)
        filename = f"{symbol}-1m-{month}.zip"
        url = f"https://data.binance.vision/data/spot/monthly/klines/{symbol}/1m/{filename}"
        local = directory / filename
        checksum_path = directory / f"{filename}.CHECKSUM"
        if local.exists() and checksum_path.exists():
            payload, checksum = local.read_bytes(), checksum_path.read_bytes()
        else:
            payload = _download(url, 50_000_000)
            checksum = _download(url + ".CHECKSUM", 4096)
        digest = hashlib.sha256(payload).hexdigest()
        tokens = checksum.decode("utf-8").strip().split()
        if len(tokens) < 2 or tokens[0].lower() != digest or tokens[-1].lstrip("*") != filename:
            raise ValueError(f"Échec de la vérification SHA-256 : {filename}.")
        market, quality = archive_to_market(payload, symbol, month)
        local.write_bytes(payload)
        checksum_path.write_bytes(checksum)
        destination = directory / f"{symbol}-{month}-market.csv"
        market.to_csv(destination, index=False, float_format="%.12g")
        manifest = {
            "source": "Binance Vision",
            "source_documentation": SOURCE_URL,
            "archive_url": url,
            "checksum_url": url + ".CHECKSUM",
            "sha256": digest,
            "market_csv_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "data_license": DATA_LICENSE,
            "terms_url": TERMS_URL,
            "accessed_utc": datetime.now(UTC).isoformat(),
            "research_use": "non-commercial educational historical research",
            "derived_results_license": "CC BY-NC-SA 4.0",
            **quality,
        }
        destination.with_suffix(".json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        paths.append(destination)
    return paths
