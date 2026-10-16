"""Parcours utilisateur : données, rapports reproductibles et erreurs lisibles."""

import json

import pandas as pd
import pytest

from execution_cost_analytics.cli import main


def test_generate_data_creates_a_reproducible_csv(tmp_path, capsys):
    destination = tmp_path / "data" / "market.csv"
    arguments = ["generate-data", "--days", "4", "--buckets", "4", "--seed", "13"]

    assert main([*arguments, "--output", str(destination)]) == 0
    output = capsys.readouterr()
    assert "16 créneaux fictifs" in output.out
    assert not output.err
    market = pd.read_csv(destination, parse_dates=["timestamp"])
    assert len(market) == 16
    assert market["session"].nunique() == 4
    assert set(market.columns) == {
        "timestamp",
        "session",
        "bucket",
        "mid_price",
        "market_volume",
        "spread_bps",
    }
    assert market.groupby("session").size().eq(4).all()

    repeated = tmp_path / "repeated.csv"
    assert main([*arguments, "--output", str(repeated)]) == 0
    assert destination.read_bytes() == repeated.read_bytes()


def test_demo_and_generate_then_run_produce_equivalent_statistics(tmp_path, capsys):
    demo_directory = tmp_path / "demo"
    csv_directory = tmp_path / "from_csv"
    source = tmp_path / "market.csv"
    generation = ["--days", "4", "--buckets", "4", "--seed", "13"]
    parameters = [
        "--train-days",
        "2",
        "--lookback",
        "2",
        "--quantity",
        "1000",
        "--side",
        "sell",
        "--participation",
        "0.05",
    ]

    assert main(["demo", *generation, *parameters, "--output-dir", str(demo_directory)]) == 0
    demo_output = capsys.readouterr()
    assert "Rapport :" in demo_output.out
    assert all(strategy in demo_output.out for strategy in ["TWAP", "VWAP", "POV"])
    assert not demo_output.err
    assert main(["generate-data", *generation, "--output", str(source)]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "run",
                "--input",
                str(source),
                *parameters,
                "--output-dir",
                str(csv_directory),
            ]
        )
        == 0
    )
    run_output = capsys.readouterr()
    assert "Rapport :" in run_output.out
    assert not run_output.err

    tables = [
        "summary",
        "aggregate_summary",
        "fills",
        "forecast_metrics",
        "sensitivity",
        "volume_profiles",
    ]
    figures = [
        "execution_paths",
        "cost_decomposition",
        "volume_forecast",
        "impact_sensitivity",
    ]
    for directory in [demo_directory, csv_directory]:
        report = (directory / "RESULTATS.md").read_text(encoding="utf-8")
        for name in figures:
            path = directory / "figures" / f"{name}.png"
            assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
            assert f"figures/{name}.png" in report
        for name in tables:
            assert (directory / f"{name}.csv").stat().st_size > 0
        metadata = json.loads((directory / "experiment.json").read_text(encoding="utf-8"))
        assert metadata["quantity"] == 1000
        assert metadata["side"] == "sell"
        assert metadata["initial_training_days"] == 2
        assert metadata["lookback"] == 2
        assert len(metadata["evaluated_sessions"]) == 2
        assert metadata["n_buckets"] == 4
        assert {"python", "numpy", "pandas", "matplotlib"} <= metadata["software"].keys()

    for name in tables:
        demo = pd.read_csv(demo_directory / f"{name}.csv")
        from_csv = pd.read_csv(csv_directory / f"{name}.csv")
        # L'aller-retour CSV peut modifier les derniers bits des flottants.
        pd.testing.assert_frame_equal(demo, from_csv, rtol=1e-8, atol=1e-7)
    demo_metadata = json.loads((demo_directory / "experiment.json").read_text(encoding="utf-8"))
    csv_metadata = json.loads((csv_directory / "experiment.json").read_text(encoding="utf-8"))
    assert demo_metadata["data_type"] == "synthetic"
    assert demo_metadata["seed"] == 13
    assert csv_metadata["input_file"] == source.name
    assert demo_metadata["config"] == csv_metadata["config"]


def test_run_explains_malformed_data_without_creating_a_report(tmp_path, capsys):
    malformed = tmp_path / "malformed.csv"
    malformed.write_text(
        "timestamp,session,bucket,mid_price,spread_bps\n2026-01-05 09:30,2026-01-05,0,100,2\n",
        encoding="utf-8",
    )
    destination = tmp_path / "invalid_report"
    with pytest.raises(SystemExit) as error:
        main(["run", "--input", str(malformed), "--output-dir", str(destination)])
    assert error.value.code == 2
    output = capsys.readouterr()
    assert "Erreur :" in output.err
    assert "market_volume" in output.err
    assert "Traceback" not in output.err
    assert not (destination / "RESULTATS.md").exists()


def test_development_study_is_explicitly_exploratory(tmp_path, capsys):
    destination = tmp_path / "study"
    assert (
        main(
            [
                "study",
                "--split",
                "dev",
                "--paths",
                "1",
                "--bootstrap-reps",
                "50",
                "--output-dir",
                str(destination),
            ]
        )
        == 0
    )
    metadata = json.loads((destination / "experiment.json").read_text(encoding="utf-8"))
    assert metadata["split"] == "development"
    assert metadata["analysis_status"] == "exploratory"
    assert metadata["executed_seeds"] == [41000]
    comparison = pd.read_csv(destination / "comparisons.csv")
    assert not comparison["is_primary"].any()
    assert "160 observations" in capsys.readouterr().out
