"""Régénérer les rapports V2 depuis les observations exportées, sans nouvelle simulation."""

import json
from pathlib import Path

import pandas as pd

from execution_cost_analytics.study import StudyResult, grid_invariance_check, summarize_study
from execution_cost_analytics.study_reporting import write_study_report

ROOT = Path(__file__).resolve().parents[1]


def refresh(directory: Path) -> None:
    metadata = json.loads((directory / "experiment.json").read_text(encoding="utf-8"))
    tables = {
        name: pd.read_csv(directory / f"{name}.csv")
        for name in ["summary", "forecast_metrics", "sample_fills"]
    }
    split = "test" if metadata.get("analysis_status") == "pre_specified_test" else "descriptive"
    aggregate, comparisons = summarize_study(tables["summary"], metadata["protocol"], split=split)
    result = StudyResult(
        **tables,
        aggregate=aggregate,
        comparisons=comparisons,
        grid_check=grid_invariance_check(metadata["protocol"]),
        metadata=metadata,
    )
    print(write_study_report(result, directory))


if __name__ == "__main__":
    for folder in ["study", "real"]:
        refresh(ROOT / "reports" / folder)
