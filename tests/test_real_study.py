"""Rejet précoce d'entrées historiques incohérentes, avec données synthétiques."""

import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from execution_cost_analytics import real_study


def write_synthetic_market(directory, first_day="2026-01-01"):
    """Une forme mensuelle plausible, sans aucune cotation de marché réelle."""
    timestamps = pd.date_range(first_day, periods=31 * 48, freq="30min")
    market = pd.DataFrame(
        {
            "timestamp": timestamps,
            "session": timestamps.strftime("%Y-%m-%d"),
            "bucket": np.tile(np.arange(48), 31),
            "mid_price": 100.0,
            "market_volume": 100_000,
            "spread_bps": 2.0,
            "open_price": 99.9,
            "close_price": 100.1,
        }
    )
    path = directory / "BTCUSDT-2026-01-market.csv"
    market.to_csv(path, index=False)
    manifest = {
        "symbol": "BTCUSDT",
        "month": "2026-01",
        "missing_minutes": 0,
        "duplicate_minutes": 0,
        "market_csv_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    path.with_suffix(".json").write_text(json.dumps(manifest), encoding="utf-8")
    return path, market


@pytest.fixture
def prohibit_calculation(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("L'entrée invalide doit être rejetée avant tout calcul d'étude.")

    monkeypatch.setattr(real_study, "forecast_volume_profile", fail_if_called)


def test_out_of_month_csv_is_rejected_despite_matching_hash_and_january_manifest(
    tmp_path, prohibit_calculation
):
    path, _ = write_synthetic_market(tmp_path, first_day="2026-03-01")
    manifest = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert manifest["month"] == "2026-01"
    assert manifest["market_csv_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="janvier 2026 complet"):
        real_study.run_public_study(tmp_path)


def test_csv_modified_after_preparation_is_rejected_by_manifest_hash(
    tmp_path, prohibit_calculation
):
    path, market = write_synthetic_market(tmp_path)
    market.loc[0, "mid_price"] = 999.0
    market.to_csv(path, index=False)
    with pytest.raises(ValueError, match="empreinte vérifiée"):
        real_study.run_public_study(tmp_path)


def test_missing_public_data_is_rejected_before_calculation(tmp_path, prohibit_calculation):
    with pytest.raises(ValueError, match="Données publiques absentes"):
        real_study.run_public_study(tmp_path)
