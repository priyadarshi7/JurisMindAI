# 07 — Quantitative Analysis Engine

> **Source:** Blueprint §7 (Quantitative Analysis Engine), §2 (backtesting caveat), §20.
> **Status:** Specification-derived.

---

## The governing rule

> **The LLM should never be the source of truth for numerical calculations. The agent invokes
> deterministic quantitative tools.** (§7)

❗ §20: **"Do not make the LLM the calculator. Numerical truth comes from deterministic tools."**

The agent **chooses** a calculation. It never **performs** one.

---

## Flow

```
LangGraph
  → Tool call
  → Quant Engine
  → Market-data store
  → Deterministic calculation
  → Structured result
  → LangGraph state   (quantitative_results)
```

The result re-enters state as a **structured object**, consistent with the §6 guardrail that nodes
exchange typed outputs. A number that reaches the report as free text somewhere in the middle of this
chain has escaped the guarantee.

---

## Initial tools (§7)

| Tool | Computes |
|---|---|
| `calculate_returns` | Returns over a period |
| `calculate_volatility` | Volatility |
| `calculate_sharpe` | Sharpe ratio |
| `calculate_max_drawdown` | Maximum drawdown |
| `calculate_beta` | Beta vs a benchmark |
| `calculate_correlation` | Correlation between series |
| `compare_assets` | Cross-asset comparison |
| `event_study` | Event-window abnormal performance |
| `backtest_strategy` | Strategy backtest |

These nine are the V3 deliverable. Each is implemented with Polars/Pandas + NumPy (§3) and
unit-tested against known-answer fixtures.

✅ **Resolved 2026-08-14 ([D-22](15-open-decisions.md)):**

- 🔒 All nine tools get **strict Pydantic schemas** for parameters and return values.
- 🔒 **Annualization is fixed**: daily → 252 trading days, weekly → 52, monthly → 12. No tool infers a
  convention from its input.
- 🔒 **Missing data fails loudly** — never silently forward-filled into a reported number. Same rule
  as the data layer ([D-6](15-open-decisions.md)), applied again at the tool boundary.
- 🎛️ Default benchmark: **S&P 500**. Risk-free rate is explicitly supplied by the market-data layer
  ([D-6](15-open-decisions.md)) — no hard-coded constant inside a Sharpe calculation.

---

## Event study — specified contract (§7)

The spec gives this one concretely:

> For an earnings event, calculate a **pre-event baseline** and post-event windows such as **+1, +3,
> +5, and +20 trading days**, including **absolute and benchmark-adjusted returns** and **volume and
> volatility changes**.

| Element | Requirement |
|---|---|
| Pre-event baseline | Required |
| Post-event windows | +1, +3, +5, +20 **trading days** (not calendar days) |
| Return measures | Absolute **and** benchmark-adjusted |
| Additional measures | Volume change, volatility change |

This tool is what answers the §2 example question *"Why did NVIDIA outperform the S&P 500 after its
latest earnings event?"* — note that the question demands a benchmark-adjusted number, which is why
benchmark adjustment is in the contract rather than optional.

---

## Backtesting requirements (§7)

All six are mandatory. Backtesting is the highest-risk capability in the product because its output
looks like a prediction and is not one.

| # | Requirement | Why it matters |
|---|---|---|
| 1 | **Train/in-sample vs out-of-sample separation** | Without it, reported performance is curve-fitting, not evidence |
| 2 | **Walk-forward validation where appropriate** | Tests whether the strategy survives regime change, not just one split |
| 3 | **Transaction costs and slippage assumptions** | Strategies that look profitable gross are routinely unprofitable net |
| 4 | **No look-ahead bias** | Using information not available at the decision time invalidates everything downstream |
| 5 | **No survivorship-bias shortcuts where avoidable** | A universe of only-surviving companies inflates every return statistic |
| 6 | **Clearly distinguish historical analysis from future prediction** | Product-boundary requirement, not just methodology |

### Look-ahead bias and the data model

Requirement 4 is enforced structurally, not by discipline. The `filing_date` metadata field
([03-data-sources.md](03-data-sources.md)) is the primary defence: a document must never be usable as
evidence for a decision point that precedes its filing date. The same applies to market data —
point-in-time correctness of the market-data store is a **precondition** for any backtest claim.

✅ **Resolved 2026-08-14 ([D-6](15-open-decisions.md)):** every market-data record carries
`timestamp`, `observed_at`, `effective_at`, `source`; backtests may only use information available
**at the simulated timestamp**. Corporate actions are stored **raw plus adjustment metadata** — a
calculation explicitly selects `raw` or `adjusted` and the two are ❗ **never silently mixed**.
Requirements 4 and 5 are honored by this contract, not by discipline at calculation time.

---

## Product boundary for quantitative output (§2)

> Backtesting is an **analytical capability**; it must include out-of-sample evaluation, transaction
> costs, slippage assumptions, and **explicit warnings about historical-data limitations**.

❗ §20: **"Do not treat backtests as predictions. Use proper validation and disclose assumptions."**

Every backtest result surfaced to a user carries:

- the assumptions used (costs, slippage, universe, period)
- the in-sample / out-of-sample split
- an explicit historical-data limitation warning

And per §2, the platform must never present **guaranteed returns**, never **autonomously execute
trades**, and never **masquerade as a personalized investment adviser**. §12 adds: **do not connect
live brokerage execution in the initial product.**

---

## Market data is not RAG

The Quant Engine reads from the **market-data store**, not from Qdrant.

| | Store | Retrieved by |
|---|---|---|
| Filings, transcripts, news | Qdrant + BM25 | Similarity + filters |
| **OHLCV, returns, volume** | **Market-data store** | **Query (ticker + date range)** |
| Macro (rates, CPI, GDP) | Quant/data layer | Query |

`datasource.txt` §3 is explicit: market prices/volume are *"quantitative tool input, not traditional
RAG."* Embedding price series would be an architectural error.

---

## Testing posture

Because this subsystem is the numerical source of truth, it is the one place in the project where
correctness is fully verifiable by ordinary unit tests — and therefore must be.

Every tool ships with:

- known-answer fixtures (hand-computed or reference-library-verified)
- edge cases: insufficient data, missing days, zero-variance series, single-observation windows
- explicit behaviour on missing data (never silently interpolate into a reported number)

✅ **Resolved 2026-08-14 ([D-22](15-open-decisions.md)): fail loudly.** Never silently forward-fill
or interpolate missing data into a reported number — same rule applied at the data layer
([D-6](15-open-decisions.md)) and here at the tool layer.

---

## ⚙ Exposure over MCP

MCP was adopted 2026-08-14 ([D-9](15-open-decisions.md)), and **this engine is its first server**.
All nine tools go behind `src/mcp/quant`.

It is the right first candidate for the same reasons it is the right subsystem to unit-test
exhaustively: typed in, typed out, deterministic, stateless, no shared graph state, and low call
volume relative to retrieval. It also becomes reusable by any MCP client outside TradeGraph.

❗ Two rules the protocol does not relax:

- **No LLM may sit inside a quant server.** MCP is transport; it is never a source of numbers. §7 and
  §20 are unchanged — *"do not make the LLM the calculator."*
- **Build the tools first, wrap them second.** The engine must exist and pass its known-answer tests
  before a protocol is placed in front of it, or a transport bug and a calculation bug become
  indistinguishable. §16 puts the engine in V3; the server follows in V3, not before.

Scope, transport, and the six constraints that must survive the boundary:
[14-mcp-assessment.md](14-mcp-assessment.md) · ⚠ [D-29](15-open-decisions.md).

---

## Evaluation (§10)

Quant-specific metrics:

- Sharpe
- Drawdown
- Turnover
- Transaction costs
- Out-of-sample performance

Note these evaluate the **strategies being analysed**, distinct from evaluating the *correctness of
the calculators*, which is unit tests. Both are required — §17 lists "Quant backtest metrics" under
Evaluation and the tool list under Quant.

Detail: [13-evaluation.md](13-evaluation.md).
