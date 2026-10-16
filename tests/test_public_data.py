"""Adaptateur public vérifié avec une archive entièrement synthétique, sans réseau."""

import hashlib
import io
import json
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
import pandas as pd
import pytest

from execution_cost_analytics import public_data

SYMBOL = "SYNTHUSDT"
MONTH = "2026-02"
FILENAME = f"{SYMBOL}-1m-{MONTH}.zip"


def make_archive(rows):
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(f"{SYMBOL}-1m-{MONTH}.csv", rows.to_csv(index=False, header=False))
    return output.getvalue()


@pytest.fixture(scope="module")
def synthetic_month():
    """28 jours de minutes artificielles ; aucune cotation réelle n'est utilisée."""
    timestamps = pd.date_range("2026-02-01", "2026-03-01", freq="min", inclusive="left")
    microseconds = timestamps.as_unit("us").asi8
    alternate = np.arange(len(timestamps)) % 2
    price = 100.0 + 10 * alternate
    volume = 1.0 + 2 * alternate
    rows = pd.DataFrame(
        {
            "open_time": microseconds,
            "open": price,
            "high": price + 1,
            "low": price - 1,
            "close": price,
            "volume": volume,
            "close_time": microseconds + 60_000_000 - 1,
            "quote_volume": price * volume,
            "trades": 10,
            "taker_base": volume / 2,
            "taker_quote": price * volume / 2,
            "ignore": 0,
        }
    )
    return rows, make_archive(rows)


def test_complete_month_aggregates_to_48_bars_per_day_with_explicit_unit(synthetic_month):
    _, payload = synthetic_month
    market, quality = public_data.archive_to_market(payload, SYMBOL, MONTH)
    assert len(market) == 28 * 48
    assert market.groupby("session").size().eq(48).all()
    for _, day in market.groupby("session", sort=False):
        np.testing.assert_array_equal(day["bucket"], np.arange(48))
    assert market["timestamp"].iloc[0] == pd.Timestamp("2026-02-01 00:00")
    assert market["timestamp"].iloc[-1] == pd.Timestamp("2026-02-28 23:30")
    assert market["timestamp"].dt.tz is None
    # La moyenne simple serait 105 ; quote/base = (15*100+45*110)/60 = 107,5.
    expected_vwap = 107.5
    expected_base_volume = 60.0
    assert public_data.MODEL_UNIT == 1e-6
    np.testing.assert_allclose(market["mid_price"], expected_vwap * 1e-6)
    np.testing.assert_allclose(market["open_price"], 100 * 1e-6)
    np.testing.assert_allclose(market["close_price"], 110 * 1e-6)
    np.testing.assert_array_equal(market["market_volume"], 60_000_000)
    np.testing.assert_allclose(
        market["mid_price"] * market["market_volume"], expected_vwap * expected_base_volume
    )
    assert quality["raw_minutes"] == quality["expected_minutes"] == 28 * 1440
    assert quality["sessions"] == 28
    assert quality["timestamp_unit"] == "us"
    assert quality["timezone"] == "UTC"
    assert quality["missing_minutes"] == quality["duplicate_minutes"] == 0
    assert quality["model_asset_unit"] == 1e-6


@pytest.mark.parametrize("defect", ["missing_minute", "duplicate_minute", "inconsistent_ohlc"])
def test_corrupted_month_is_rejected_before_conversion(synthetic_month, defect):
    rows = synthetic_month[0].copy()
    if defect == "missing_minute":
        rows = rows.drop(index=100)
    elif defect == "duplicate_minute":
        rows.iloc[100] = rows.iloc[99]
    else:
        rows.loc[100, "high"] = rows.loc[100, "open"] - 1
    with pytest.raises(ValueError, match="incomplète|OHLC"):
        public_data.archive_to_market(make_archive(rows), SYMBOL, MONTH)


def test_zero_volume_bar_uses_reference_price_without_creating_liquidity(synthetic_month):
    rows = synthetic_month[0].copy()
    rows.loc[:29, ["volume", "quote_volume", "trades", "taker_base", "taker_quote"]] = 0
    market, quality = public_data.archive_to_market(make_archive(rows), SYMBOL, MONTH)
    first = market.iloc[0]
    assert first["market_volume"] == 0
    assert first["mid_price"] == pytest.approx(110 * 1e-6)
    assert quality["zero_volume_bars"] == 1


@pytest.mark.parametrize("quote_volume", [0.0, 1_000_000.0])
def test_positive_volume_requires_trade_vwap_consistent_with_ohlc(synthetic_month, quote_volume):
    rows = synthetic_month[0].copy()
    # OHLC et volume restent valides : seule la comptabilité quote/base est corrompue.
    rows.loc[100, "quote_volume"] = quote_volume
    with pytest.raises(ValueError, match="VWAP de transactions"):
        public_data.archive_to_market(make_archive(rows), SYMBOL, MONTH)


def test_verified_download_and_local_cache_produce_identical_market(
    synthetic_month, tmp_path, monkeypatch
):
    payload = synthetic_month[1]
    digest = hashlib.sha256(payload).hexdigest()
    checksum = f"{digest}  {FILENAME}\n".encode()
    requests = []

    def fake_download(url, maximum_bytes):
        requests.append((url, maximum_bytes))
        return checksum if url.endswith(".CHECKSUM") else payload

    monkeypatch.setattr(public_data, "_download", fake_download)
    paths = public_data.fetch_public_data((SYMBOL,), MONTH, tmp_path)
    assert len(requests) == 2
    assert paths == [tmp_path / f"{SYMBOL}-{MONTH}-market.csv"]
    first_csv = paths[0].read_bytes()
    first_manifest = json.loads(paths[0].with_suffix(".json").read_text(encoding="utf-8"))
    assert first_manifest["sha256"] == digest
    assert first_manifest["symbol"] == SYMBOL
    assert first_manifest["raw_minutes"] == 28 * 1440
    assert (tmp_path / FILENAME).read_bytes() == payload
    assert (tmp_path / f"{FILENAME}.CHECKSUM").read_bytes() == checksum

    def prohibit_network(*args, **kwargs):
        raise AssertionError("Une archive vérifiée en cache ne doit pas être retéléchargée.")

    monkeypatch.setattr(public_data, "_download", prohibit_network)
    cached_paths = public_data.fetch_public_data((SYMBOL,), MONTH, tmp_path)
    assert cached_paths == paths
    assert paths[0].read_bytes() == first_csv
    cached_manifest = json.loads(paths[0].with_suffix(".json").read_text(encoding="utf-8"))
    first_manifest.pop("accessed_utc")
    cached_manifest.pop("accessed_utc")
    assert cached_manifest == first_manifest


def test_checksum_failure_does_not_save_corrupt_download(synthetic_month, tmp_path, monkeypatch):
    payload = synthetic_month[1]
    bad_checksum = f"{'0' * 64}  {FILENAME}\n".encode()

    def fake_download(url, maximum_bytes):
        return bad_checksum if url.endswith(".CHECKSUM") else payload

    monkeypatch.setattr(public_data, "_download", fake_download)
    with pytest.raises(ValueError, match="SHA-256"):
        public_data.fetch_public_data((SYMBOL,), MONTH, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_local_cache_is_reverified_before_conversion(synthetic_month, tmp_path, monkeypatch):
    payload = synthetic_month[1]
    digest = hashlib.sha256(payload).hexdigest()
    (tmp_path / FILENAME).write_bytes(payload + b"corruption locale")
    (tmp_path / f"{FILENAME}.CHECKSUM").write_text(f"{digest}  {FILENAME}\n")

    def prohibit_network(*args, **kwargs):
        raise AssertionError("Le cache présent doit être contrôlé localement.")

    monkeypatch.setattr(public_data, "_download", prohibit_network)
    with pytest.raises(ValueError, match="SHA-256"):
        public_data.fetch_public_data((SYMBOL,), MONTH, tmp_path)
    assert not (tmp_path / f"{SYMBOL}-{MONTH}-market.csv").exists()
