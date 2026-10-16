# Execution Cost Analytics

**What does a higher probability of completing an order cost when volume forecasts are wrong?**

[![CI](https://github.com/moussoulijane/execution-cost-analytics/actions/workflows/ci.yml/badge.svg)](https://github.com/moussoulijane/execution-cost-analytics/actions/workflows/ci.yml)
![Python 3.11–3.12](https://img.shields.io/badge/Python-3.11%E2%80%933.12-blue)
[![Code: MIT](https://img.shields.io/badge/Code-MIT-green)](LICENSE)

A reproducible Python study comparing TWAP, forecast VWAP, POV and a causal catch-up policy. It combines controlled simulations, paired comparisons and a chronological evaluation on public BTC/ETH transaction data. The aim is to understand execution trade-offs under explicit assumptions.

**English** · [Présentation et guide en français](README.fr.md)

## Findings

| Question | Reference result | Interpretation |
| --- | --- | --- |
| Does ADAPTIVE improve on VWAP? | Mean saving **0.109 bp**, paired bootstrap 95% CI **[−0.127, +0.371]**; both complete **82.5%** of orders. | No established economically useful gain in the predefined primary comparison. |
| What does deadline urgency cost? | VWAP completion rises from **0% to 82.5%**, with **2.005 bp** more mean explicit cost. | Completion has a measurable price; acceptability requires a client objective. |
| Does public history support ADAPTIVE? | Higher mean implementation shortfall than VWAP on **both BTC and ETH** in the highlighted comparison. | Historical results do not confirm superiority; costs remain model dependent. |

The first two rows use realized volume at 55% of forecast, an order of 10% of forecast daily volume and square-root impact. The first compares policies under a common deadline; the second compares soft and common deadlines for VWAP. Positive savings mean `IS_VWAP − IS_ADAPTIVE`. One basis point is 0.01% of initial order notional.

![Explicit execution cost and probability of completing the order](reports/study/figures/completion_cost.png)

See the [controlled study](reports/study/RESULTATS.md), [historical results](reports/real/RESULTATS.md) and [executed notebook](notebooks/02_volume_uncertainty.ipynb) for full comparisons. Detailed reports and chart labels are in French.

## Experimental design

- **Shared market paths:** four policies, five scenarios, two order sizes, two impact specifications and two deadline rules. The 12,800 strategy observations contain **80 independent evaluation paths per cell**, not 12,800 independent experiments.
- **Separated development and evaluation:** forecasts use prior information; development seeds differ from evaluation seeds. One primary contrast and illustrative decision thresholds are fixed in a [local protocol](docs/PROTOCOLE_V2.md) before the full evaluation. This is not independent preregistration.
- **Common constraints:** all policies face identical capacity. Deadline urgency raises the participation cap from 15% to 40% during the final `ceil(20% × B)` intervals. Spread, impact and fees still apply; completion is never guaranteed.
- **Causal catch-up:** ADAPTIVE adds prior execution shortfall to a VWAP schedule. Its planner receives past fills, not future market data. Impact uses realized local participation; subdivision checks guard against an artificial benefit from finer slicing.
- **Uncertainty:** paired bootstrap intervals compare costs within paths. Completion checks also use conservative Wilson bounds; identical observed completion rates do not establish non-inferiority.

## Run locally

Requires **Python 3.11 or 3.12**.

```bash
git clone https://github.com/moussoulijane/execution-cost-analytics.git
cd execution-cost-analytics
python -m venv .venv
```

Activate on **Windows PowerShell**:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell restricts activation, use `.\.venv\Scripts\python.exe` instead of `python` in the commands below.

Or on **macOS/Linux**:

```bash
source .venv/bin/activate
```

Then, on either platform:

```bash
python -m pip install -e ".[dev]"
python -m execution_cost_analytics study --split dev --paths 2 --bootstrap-reps 100 --output-dir outputs/exploration
```

This quick run is explicitly exploratory. Reference outputs are committed; reading reports and running notebooks requires no raw-data download. Reproduce the full controlled study with:

```bash
python -m execution_cost_analytics study
```

Download, validate and evaluate the public archives with:

```bash
python -m execution_cost_analytics fetch-public-data --symbols BTCUSDT ETHUSDT --month 2026-01 --output-dir data/public
python -m execution_cost_analytics real-study --input-dir data/public --output-dir reports/real
```

## Public data and limits

Binance Vision one-minute BTCUSDT/ETHUSDT archives for January 2026 are checked against official SHA-256 checksums, missing minutes and OHLC/VWAP consistency. Fourteen initial days precede **17 chronologically evaluated days per asset** using rolling forecasts. Assets are reported separately.

Execution reference prices are **transaction VWAPs, not bid/ask midpoints**. The 2 bp spread, volatility and impact parameters are hypothetical, not calibrated execution estimates. There is no order book, queue, latency, permanent impact or price feedback. Historical intervals assume temporal independence that has not been established. OHLCV observations alone cannot identify the causal impact of these orders.

## Explore and verify

- [Ten-session French learning guide](docs/GUIDE_PAS_A_PAS.md), with exercises and solutions.
- [Notebook 01: execution mechanics](notebooks/01_execution_cost_analysis.ipynb) and [Notebook 02: uncertainty and public data](notebooks/02_volume_uncertainty.ipynb).
- [Methodology](docs/METHODOLOGIE.md), [protocol parameters](docs/PROTOCOLE_V2.json) and [sources/provenance](docs/SOURCES.md).
- [`src/execution_cost_analytics/`](src/execution_cost_analytics/): policies, simulator, analytics, studies and CLI; [`tests/`](tests/): hand-worked cases, invariants and integration checks.

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python scripts/execute_notebook.py
```

The [GitHub Actions workflow](.github/workflows/ci.yml) runs these checks on Python 3.11 and 3.12. Tests establish computational consistency, not economic validity.

## Licenses

Code: [MIT](LICENSE). Binance-derived historical outputs and the second notebook have separate **CC BY-NC-SA 4.0** terms and attribution: [historical reports](reports/real/LICENSE.md), [notebooks](notebooks/LICENSE.md), [source conditions](docs/SOURCES.md). Raw archives and exploratory outputs are excluded from Git.
