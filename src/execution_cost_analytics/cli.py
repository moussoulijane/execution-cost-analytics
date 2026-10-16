"""Interface en ligne de commande, volontairement sans service externe."""

import argparse
from pathlib import Path

import pandas as pd

from .data import generate_market_data
from .experiment import run_experiment
from .reporting import write_report


def _experiment_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    parser.add_argument("--quantity", type=int, default=50_000)
    parser.add_argument("--side", choices=["buy", "sell"], default="buy")
    parser.add_argument("--train-days", type=int, default=30)
    parser.add_argument("--lookback", type=int, default=20)
    parser.add_argument("--participation", type=float, default=0.03)
    parser.add_argument("--max-participation", type=float, default=0.15)
    parser.add_argument("--impact-coefficient", type=float, default=0.05)
    parser.add_argument("--impact-exponent", type=float, choices=[0.5, 1.0], default=0.5)
    parser.add_argument("--deadline-mode", choices=["soft", "common_deadline"], default="soft")
    parser.add_argument("--fee-bps", type=float, default=0.5)
    parser.add_argument("--daily-volatility", type=float, default=0.02)


def main(argv: list[str] | None = None) -> int:
    """Retourner 0 au succès ; argparse explique les erreurs d'entrée."""
    parser = argparse.ArgumentParser(description="Laboratoire pédagogique de coûts d'exécution.")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Générer un marché fictif et tous les rapports.")
    demo.add_argument("--seed", type=int, default=42)
    demo.add_argument("--days", type=int, default=40)
    demo.add_argument("--buckets", type=int, default=26)
    _experiment_arguments(demo)
    generate = commands.add_parser("generate-data", help="Générer un CSV de marché fictif.")
    generate.add_argument("--output", type=Path, default=Path("data/synthetic_market.csv"))
    generate.add_argument("--seed", type=int, default=42)
    generate.add_argument("--days", type=int, default=40)
    generate.add_argument("--buckets", type=int, default=26)
    run = commands.add_parser("run", help="Évaluer un CSV respectant le schéma documenté.")
    run.add_argument("--input", type=Path, required=True)
    _experiment_arguments(run)
    study = commands.add_parser(
        "study", help="Reproduire le protocole V2 et ses comparaisons appariées."
    )
    study.add_argument("--output-dir", type=Path, default=Path("reports/study"))
    study.add_argument("--split", choices=["dev", "test"], default="test")
    study.add_argument("--paths", type=int)
    study.add_argument("--bootstrap-reps", type=int)
    study.add_argument("--protocol", type=Path)
    fetch = commands.add_parser(
        "fetch-public-data", help="Télécharger et vérifier les archives publiques."
    )
    fetch.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    fetch.add_argument("--month", default="2026-01")
    fetch.add_argument("--output-dir", type=Path, default=Path("data/public"))
    real = commands.add_parser(
        "real-study", help="Confronter les modèles aux données intraday publiques."
    )
    real.add_argument("--input-dir", type=Path, default=Path("data/public"))
    real.add_argument("--output-dir", type=Path, default=Path("reports/real"))
    args = parser.parse_args(argv)
    try:
        if args.command == "fetch-public-data":
            from .public_data import fetch_public_data

            for path in fetch_public_data(tuple(args.symbols), args.month, args.output_dir):
                print(path)
            return 0
        if args.command in {"study", "real-study"}:
            from .study_reporting import write_study_report

            if args.command == "study":
                from .study import run_study

                split = "development" if args.split == "dev" else args.split
                result = run_study(args.protocol, split, args.paths, args.bootstrap_reps)
            else:
                from .real_study import run_public_study

                result = run_public_study(args.input_dir)
            report = write_study_report(result, args.output_dir)
            print(f"{len(result.summary)} observations de stratégie ; rapport : {report}")
            return 0
        if args.command == "generate-data":
            market = generate_market_data(args.days, args.buckets, args.seed)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            market.to_csv(args.output, index=False)
            print(f"{len(market)} créneaux fictifs écrits dans {args.output}")
            return 0
        if args.command == "demo":
            market = generate_market_data(args.days, args.buckets, args.seed)
        else:
            market = pd.read_csv(args.input, parse_dates=["timestamp"])
        parameters = {
            name: getattr(args, name)
            for name in [
                "quantity",
                "side",
                "train_days",
                "lookback",
                "participation",
                "max_participation",
                "impact_coefficient",
                "fee_bps",
                "daily_volatility",
                "impact_exponent",
                "deadline_mode",
            ]
        }
        result = run_experiment(market, **parameters)
        if args.command == "demo":
            result.metadata.update(
                {"data_type": "synthetic", "seed": args.seed, "generated_days": args.days}
            )
        else:
            result.metadata["input_file"] = args.input.name
        report = write_report(result, args.output_dir)
        print(result.aggregate_summary.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
        print(f"\nRapport : {report}")
        return 0
    except (ValueError, OSError, KeyError) as error:
        parser.exit(2, f"Erreur : {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
