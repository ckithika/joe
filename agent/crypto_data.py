"""Crypto-specific data intelligence — Tier 1, 2, and 3 on-chain & market metrics."""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# Rate limiting: minimum seconds between requests to the same API
_RATE_LIMIT_SECONDS = 1.0
_last_request_times: dict[str, float] = {}


def _rate_limit(api_name: str):
    """Simple per-API rate limiter."""
    now = time.time()
    last = _last_request_times.get(api_name, 0)
    wait = _RATE_LIMIT_SECONDS - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_request_times[api_name] = time.time()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Data Classes
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class FearGreedIndex:
    """Crypto Fear & Greed Index (0-100)."""
    value: int              # 0 = extreme fear, 100 = extreme greed
    classification: str     # "Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed"
    timestamp: str
    history_7d: list[int] = field(default_factory=list)


@dataclass
class DominanceData:
    """BTC and ETH market dominance percentages."""
    btc_dominance: float        # e.g. 52.3
    eth_dominance: float        # e.g. 17.1
    total_market_cap: float     # total crypto market cap in USD
    btc_market_cap: float
    eth_market_cap: float


@dataclass
class FundingRate:
    """Perpetual futures funding rate for a symbol."""
    symbol: str
    rate: float                 # e.g. 0.0001 = 0.01%
    annualized: float           # annualized rate
    next_funding_time: str
    direction: str              # "long_pay" or "short_pay" or "neutral"


@dataclass
class OpenInterestData:
    """Open interest for a symbol."""
    symbol: str
    open_interest: float        # in contracts
    open_interest_usd: float    # in USD
    change_24h_pct: float       # 24h change percentage


@dataclass
class StablecoinSupply:
    """Stablecoin market supply data."""
    usdt_market_cap: float
    usdc_market_cap: float
    total_stablecoin_cap: float
    usdt_dominance: float       # % of total stablecoin market


@dataclass
class HashRateData:
    """Bitcoin network hash rate."""
    hash_rate: float            # TH/s
    difficulty: float
    block_height: int
    timestamp: str


@dataclass
class DefiSnapshot:
    """DeFi ecosystem snapshot."""
    total_tvl: float            # Total Value Locked in USD
    top_protocols: list[dict]   # [{name, tvl, change_1d}]
    eth_tvl: float              # ETH chain TVL
    stablecoin_tvl: float       # Stablecoins in DeFi


@dataclass
class GasData:
    """Ethereum gas metrics."""
    gas_price_gwei: float       # current gas price
    base_fee_gwei: float        # EIP-1559 base fee
    priority_fee_gwei: float    # priority/tip fee


@dataclass
class WhaleActivity:
    """Large transaction activity."""
    large_txns_24h: int         # transactions > $1M
    net_exchange_flow: str      # "inflow" or "outflow"
    notable_txns: list[dict]    # [{amount, from_type, to_type, symbol}]


@dataclass
class CorrelationMatrix:
    """Asset correlation data."""
    pairs: dict[str, float]     # {"BTC-ETH": 0.85, "BTC-SPY": 0.42, ...}
    period_days: int


@dataclass
class CryptoIntelligence:
    """Combined crypto intelligence report."""
    # Tier 1
    fear_greed: FearGreedIndex | None = None
    dominance: DominanceData | None = None
    btc_funding: FundingRate | None = None
    eth_funding: FundingRate | None = None
    btc_open_interest: OpenInterestData | None = None
    eth_open_interest: OpenInterestData | None = None

    # Tier 2
    stablecoin_supply: StablecoinSupply | None = None
    hash_rate: HashRateData | None = None
    liquidation_estimate: dict | None = None

    # Tier 3
    defi: DefiSnapshot | None = None
    gas: GasData | None = None
    whale_activity: WhaleActivity | None = None
    correlations: CorrelationMatrix | None = None

    timestamp: str = ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Tier 1: Core Metrics (Free APIs, no keys required)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def fetch_fear_greed() -> FearGreedIndex | None:
    """Fetch Crypto Fear & Greed Index from alternative.me (free, no key).

    The Fear & Greed Index is a daily indicator from 0-100 that measures
    the overall emotional state of the crypto market.

    How it's calculated:
    - Volatility (25%): unusual volatility = fearful market
    - Market Momentum/Volume (25%): high buying volume = greedy market
    - Social Media (15%): crypto mentions and engagement rates
    - Surveys (15%): weekly crypto polls
    - BTC Dominance (10%): rising dominance = fear (fleeing to BTC safety)
    - Google Trends (10%): crypto search volume

    Scale:
    - 0-24: Extreme Fear (good buying opportunity historically)
    - 25-49: Fear
    - 50: Neutral
    - 51-74: Greed
    - 75-100: Extreme Greed (market may be overheated)
    """
    try:
        _rate_limit("alternative.me")
        resp = requests.get(
            "https://api.alternative.me/fng/",
            params={"limit": 8, "format": "json"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not data:
            return None

        current = data[0]
        history = [int(d["value"]) for d in data[1:8]]

        return FearGreedIndex(
            value=int(current["value"]),
            classification=current["value_classification"],
            timestamp=current.get("timestamp", ""),
            history_7d=history,
        )
    except Exception as e:
        logger.warning("Fear & Greed fetch failed: %s", e)
        return None


def fetch_dominance() -> DominanceData | None:
    """Fetch BTC/ETH dominance from CoinGecko (free, no key needed).

    Market Dominance measures what % of the total crypto market cap belongs
    to a specific coin. BTC dominance is the most-watched metric.

    What it means:
    - Rising BTC dominance: money flowing into BTC (risk-off / flight to safety)
    - Falling BTC dominance: money flowing into altcoins (risk-on / "alt season")
    - Typical range: BTC 40-65%, ETH 15-22%

    Trading implications:
    - BTC dominance > 60%: Focus on BTC, avoid small altcoins
    - BTC dominance < 45%: Altcoin opportunities may be strongest
    - Rapid dominance shifts often precede major market moves
    """
    try:
        _rate_limit("coingecko")
        resp = requests.get(
            "https://api.coingecko.com/api/v3/global",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})

        market_cap_pct = data.get("market_cap_percentage", {})
        total_cap = data.get("total_market_cap", {}).get("usd", 0)

        btc_dom = market_cap_pct.get("btc", 0)
        eth_dom = market_cap_pct.get("eth", 0)

        return DominanceData(
            btc_dominance=round(btc_dom, 2),
            eth_dominance=round(eth_dom, 2),
            total_market_cap=total_cap,
            btc_market_cap=total_cap * btc_dom / 100 if total_cap else 0,
            eth_market_cap=total_cap * eth_dom / 100 if total_cap else 0,
        )
    except Exception as e:
        logger.warning("Dominance fetch failed: %s", e)
        return None


def fetch_funding_rate(symbol: str = "BTCUSDT") -> FundingRate | None:
    """Fetch perpetual futures funding rate from Binance (free, no key).

    Funding rates are periodic payments between long and short traders in
    perpetual futures markets. They keep the futures price close to spot price.

    How it works:
    - Positive rate: longs pay shorts (market is bullish / overleveraged long)
    - Negative rate: shorts pay longs (market is bearish / overleveraged short)
    - Typical range: -0.01% to +0.03% per 8 hours
    - Payments happen every 8 hours (00:00, 08:00, 16:00 UTC)

    Trading signals:
    - Very high positive rate (>0.05%): Market may be overheated, correction likely
    - Very negative rate (<-0.01%): Shorts are crowded, squeeze potential
    - Neutral (around 0.01%): Balanced market, no strong lean
    - Annualized: multiply by 3 * 365 for yearly equivalent
    """
    try:
        _rate_limit("binance")
        resp = requests.get(
            "https://fapi.binance.com/fapi/v1/fundingRate",
            params={"symbol": symbol, "limit": 1},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return None

        rate = float(data[0]["fundingRate"])
        annualized = rate * 3 * 365 * 100  # 3 times daily, 365 days, as percentage

        if rate > 0.0001:
            direction = "long_pay"
        elif rate < -0.0001:
            direction = "short_pay"
        else:
            direction = "neutral"

        return FundingRate(
            symbol=symbol,
            rate=rate,
            annualized=round(annualized, 2),
            next_funding_time=data[0].get("fundingTime", ""),
            direction=direction,
        )
    except Exception as e:
        logger.warning("Funding rate fetch failed for %s: %s", symbol, e)
        return None


def fetch_open_interest(symbol: str = "BTCUSDT") -> OpenInterestData | None:
    """Fetch open interest from Binance Futures (free, no key).

    Open Interest (OI) is the total number of outstanding futures/options
    contracts that haven't been settled. It shows how much money is in the market.

    What it means:
    - Rising OI + Rising Price: New money entering, strong trend continuation
    - Rising OI + Falling Price: Short sellers entering, bearish pressure
    - Falling OI + Rising Price: Short covering rally (may not sustain)
    - Falling OI + Falling Price: Longs exiting, capitulation

    Key levels:
    - All-time high OI: lots of leverage in system, big move incoming
    - Rapid OI increase: volatile move likely (but direction unclear)
    - OI dropping sharply: forced liquidations happening
    """
    try:
        _rate_limit("binance")
        resp = requests.get(
            "https://fapi.binance.com/fapi/v1/openInterest",
            params={"symbol": symbol},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        oi = float(data.get("openInterest", 0))

        # Get current price for USD conversion
        price_resp = requests.get(
            "https://fapi.binance.com/fapi/v1/ticker/price",
            params={"symbol": symbol},
            timeout=10,
        )
        price_resp.raise_for_status()
        price = float(price_resp.json().get("price", 0))
        oi_usd = oi * price

        # Get 24h stats for change calculation
        stats_resp = requests.get(
            "https://fapi.binance.com/fapi/v1/ticker/24hr",
            params={"symbol": symbol},
            timeout=10,
        )
        stats_resp.raise_for_status()
        stats = stats_resp.json()
        change_pct = float(stats.get("priceChangePercent", 0))

        return OpenInterestData(
            symbol=symbol,
            open_interest=oi,
            open_interest_usd=round(oi_usd, 2),
            change_24h_pct=change_pct,
        )
    except Exception as e:
        logger.warning("Open interest fetch failed for %s: %s", symbol, e)
        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Tier 2: Advanced Metrics
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def fetch_stablecoin_supply() -> StablecoinSupply | None:
    """Fetch stablecoin market data from CoinGecko (free).

    Stablecoins (USDT, USDC, DAI, etc.) are crypto tokens pegged to $1.
    Their total supply indicates how much "dry powder" is sitting on the
    sidelines ready to buy crypto.

    What it means:
    - Rising stablecoin supply: More cash entering crypto ecosystem (bullish)
    - Falling stablecoin supply: Cash leaving crypto (bearish)
    - USDT dominance: If USDT is very dominant, market relies on one stablecoin
    - Stablecoin ratio (total crypto cap / stablecoin cap): Lower = more buying power

    Key insight:
    - Large stablecoin mints (billions created) often precede rallies
    - Stablecoin burns (redeemed for fiat) often precede drops
    """
    try:
        _rate_limit("coingecko")
        # Fetch USDT and USDC market caps
        resp = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids": "tether,usd-coin",
                "vs_currencies": "usd",
                "include_market_cap": "true",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        usdt_cap = data.get("tether", {}).get("usd_market_cap", 0)
        usdc_cap = data.get("usd-coin", {}).get("usd_market_cap", 0)
        total = usdt_cap + usdc_cap
        usdt_dom = (usdt_cap / total * 100) if total > 0 else 0

        return StablecoinSupply(
            usdt_market_cap=usdt_cap,
            usdc_market_cap=usdc_cap,
            total_stablecoin_cap=total,
            usdt_dominance=round(usdt_dom, 1),
        )
    except Exception as e:
        logger.warning("Stablecoin supply fetch failed: %s", e)
        return None


def fetch_hash_rate() -> HashRateData | None:
    """Fetch Bitcoin hash rate from Blockchain.com (free, no key).

    Hash Rate measures the total computing power securing the Bitcoin network.
    It's measured in terahashes per second (TH/s).

    What it means:
    - Rising hash rate: Miners are investing in hardware (bullish confidence)
    - Falling hash rate: Miners shutting down (less profitable / bearish)
    - Hash rate hits ATH: Network is most secure ever, miners expect higher prices
    - Sudden drops: Mining farm shutdown, regulatory action, or hardware failure

    Mining economics:
    - Hash rate up + price down: Miners may sell to cover costs (short-term bearish)
    - Hash rate up + price up: Healthy growth, miners profitable
    - After halvings: hash rate dips then recovers as miners adapt

    Difficulty adjusts every ~2016 blocks (~2 weeks) to keep 10-minute block times.
    """
    try:
        _rate_limit("blockchain.com")
        resp = requests.get(
            "https://api.blockchain.info/stats",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        return HashRateData(
            hash_rate=round(data.get("hash_rate", 0) / 1e12, 2),  # Convert to TH/s
            difficulty=data.get("difficulty", 0),
            block_height=data.get("n_blocks_total", 0),
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.warning("Hash rate fetch failed: %s", e)
        return None


def estimate_liquidation_levels(symbol: str = "BTCUSDT") -> dict | None:
    """Estimate liquidation clusters from funding rate and OI data.

    Liquidation happens when a leveraged trader's losses exceed their margin.
    The exchange force-closes their position, which creates cascading price moves.

    What it means:
    - High OI + high funding rate: Lots of leveraged longs, liquidation risk below
    - High OI + negative funding: Lots of leveraged shorts, squeeze risk above
    - Liquidation cascades cause sudden 5-20% moves in seconds

    This is an estimate based on typical leverage levels (5x-20x).
    Professional tools like CoinGlass provide exact liquidation heatmaps.

    Trading implications:
    - Avoid entering just before major liquidation zones
    - Liquidation flushes often create the best entry points (after the move)
    - If your position is near a liquidation cluster, reduce size
    """
    try:
        # Get current price
        _rate_limit("binance")
        resp = requests.get(
            "https://fapi.binance.com/fapi/v1/ticker/price",
            params={"symbol": symbol},
            timeout=10,
        )
        resp.raise_for_status()
        price = float(resp.json().get("price", 0))

        if price <= 0:
            return None

        # Get funding rate to estimate bias
        funding = fetch_funding_rate(symbol)

        # Estimate liquidation zones based on common leverage levels
        # Most retail uses 5x-20x leverage
        zones = {
            "current_price": price,
            "long_liquidation_zones": [
                {"leverage": "20x", "price": round(price * 0.95, 2), "description": "5% below — 20x longs liquidated"},
                {"leverage": "10x", "price": round(price * 0.90, 2), "description": "10% below — 10x longs liquidated"},
                {"leverage": "5x", "price": round(price * 0.80, 2), "description": "20% below — 5x longs liquidated"},
            ],
            "short_liquidation_zones": [
                {"leverage": "20x", "price": round(price * 1.05, 2), "description": "5% above — 20x shorts liquidated"},
                {"leverage": "10x", "price": round(price * 1.10, 2), "description": "10% above — 10x shorts liquidated"},
                {"leverage": "5x", "price": round(price * 1.20, 2), "description": "20% above — 5x shorts liquidated"},
            ],
            "bias": "long_heavy" if (funding and funding.rate > 0.0003) else
                    "short_heavy" if (funding and funding.rate < -0.0001) else "balanced",
            "risk_level": "high" if (funding and abs(funding.rate) > 0.0005) else
                          "moderate" if (funding and abs(funding.rate) > 0.0002) else "low",
        }
        return zones
    except Exception as e:
        logger.warning("Liquidation estimate failed for %s: %s", symbol, e)
        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Tier 3: Ecosystem Intelligence
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def fetch_defi_snapshot() -> DefiSnapshot | None:
    """Fetch DeFi TVL data from DefiLlama (free, no key).

    Total Value Locked (TVL) measures how much crypto is deposited in
    DeFi protocols (lending, trading, staking, etc.).

    What it means:
    - Rising TVL: More money being put to work in DeFi (bullish for ETH/DeFi tokens)
    - Falling TVL: Money leaving DeFi (bearish, or rotating to other opportunities)
    - TVL vs market cap: If TVL falls faster than prices, users are losing confidence

    Key protocols to watch:
    - Lido (liquid staking): Reflects ETH staking demand
    - Aave/Compound (lending): Shows borrowing demand
    - Uniswap/Curve (DEXs): Shows trading activity

    DeFi is mostly on Ethereum, so ETH price and DeFi health are closely linked.
    """
    try:
        # Get chain TVLs (includes total and per-chain)
        _rate_limit("defillama")
        chain_resp = requests.get("https://api.llama.fi/v2/chains", timeout=10)
        chain_resp.raise_for_status()
        chains = chain_resp.json()

        total_tvl = 0
        eth_tvl = 0
        for chain in chains:
            tvl = chain.get("tvl") or 0
            total_tvl += tvl
            if chain.get("name") == "Ethereum":
                eth_tvl = tvl

        # Get top protocols
        _rate_limit("defillama")
        protocols_resp = requests.get("https://api.llama.fi/protocols", timeout=15)
        protocols_resp.raise_for_status()
        protocols = protocols_resp.json()

        top_5 = []
        # Filter to protocols with valid TVL
        valid_protocols = [p for p in protocols if isinstance(p.get("tvl"), (int, float)) and p["tvl"] > 0]
        for p in sorted(valid_protocols, key=lambda x: x.get("tvl", 0), reverse=True)[:5]:
            change_1d = p.get("change_1d")
            top_5.append({
                "name": p.get("name", ""),
                "tvl": round(p.get("tvl", 0), 2),
                "change_1d": round(float(change_1d), 2) if change_1d is not None else 0,
            })

        return DefiSnapshot(
            total_tvl=round(total_tvl, 2),
            top_protocols=top_5,
            eth_tvl=round(eth_tvl, 2),
            stablecoin_tvl=0,
        )
    except Exception as e:
        logger.warning("DeFi snapshot fetch failed: %s", e)
        return None


def fetch_gas_data() -> GasData | None:
    """Fetch Ethereum gas prices from public RPC or Etherscan-like APIs.

    Gas is the fee you pay to do anything on Ethereum (send tokens,
    trade on Uniswap, mint NFTs, etc.). Measured in Gwei (1 Gwei = 0.000000001 ETH).

    What it means:
    - High gas (>50 Gwei): Network is very busy, lots of on-chain activity
    - Low gas (<10 Gwei): Network is quiet, less demand
    - Gas spikes: Usually from NFT mints, token launches, or market crashes
    - Sustained high gas: Strong on-chain economy (bullish for ETH)

    EIP-1559 (since Aug 2021):
    - Base fee: Minimum fee that gets burned (destroyed)
    - Priority fee: Tip to miners/validators for faster inclusion
    - When base fee is high, more ETH is burned, reducing supply (bullish for ETH)

    Trading context:
    - Very high gas often means panic selling or FOMO buying
    - Low gas during a rally: Rally may not have broad participation
    """
    # Try multiple public RPCs in order of reliability
    rpc_endpoints = [
        "https://ethereum-rpc.publicnode.com",
        "https://rpc.ankr.com/eth",
        "https://cloudflare-eth.com",
    ]

    for rpc_url in rpc_endpoints:
        try:
            _rate_limit("eth_rpc")
            resp = requests.post(
                rpc_url,
                json={"jsonrpc": "2.0", "method": "eth_gasPrice", "params": [], "id": 1},
                timeout=10,
            )
            resp.raise_for_status()
            result = resp.json()
            if "error" in result:
                continue

            gas_hex = result.get("result", "0x0")
            gas_wei = int(gas_hex, 16)
            gas_gwei = gas_wei / 1e9

            # Get base fee from latest block
            block_resp = requests.post(
                rpc_url,
                json={"jsonrpc": "2.0", "method": "eth_getBlockByNumber", "params": ["latest", False], "id": 2},
                timeout=10,
            )
            block_resp.raise_for_status()
            block = block_resp.json().get("result", {})
            base_fee_hex = block.get("baseFeePerGas", "0x0")
            base_fee_gwei = int(base_fee_hex, 16) / 1e9

            priority_fee = max(gas_gwei - base_fee_gwei, 0)

            return GasData(
                gas_price_gwei=round(gas_gwei, 4),
                base_fee_gwei=round(base_fee_gwei, 4),
                priority_fee_gwei=round(priority_fee, 4),
            )
        except Exception:
            continue

    logger.warning("Gas data fetch failed: all RPC endpoints unavailable")
    return None


def fetch_whale_activity() -> WhaleActivity | None:
    """Estimate whale activity from Blockchain.com large transactions.

    Whales are wallets holding large amounts of crypto (typically >1000 BTC
    or >10,000 ETH). Their movements often signal upcoming price action.

    What it means:
    - Whales moving to exchanges: Likely preparing to sell (bearish)
    - Whales moving from exchanges: Accumulating, removing from market (bullish)
    - Whale-to-whale transfers: OTC deals, doesn't directly affect price
    - Dormant wallets waking up: Old holders may be preparing to sell

    Types of whale moves:
    - Exchange inflow: Crypto sent TO exchanges (potential sell pressure)
    - Exchange outflow: Crypto withdrawn FROM exchanges (reducing supply)
    - Net flow: Inflows - Outflows (positive = bearish, negative = bullish)

    Note: This uses estimated data. Professional whale tracking services
    like Whale Alert, Nansen, or Glassnode provide more precise data.
    """
    try:
        _rate_limit("blockchain.com")
        # Fetch recent large transactions from Blockchain.com
        resp = requests.get(
            "https://api.blockchain.info/stats",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        # Estimate from transaction count and volume
        tx_count = data.get("n_tx", 0)
        total_btc_sent = data.get("total_btc_sent", 0) / 1e8  # satoshi to BTC
        estimated_value = data.get("estimated_transaction_volume_usd", 0)

        # Large transactions estimated as >$1M
        avg_tx_value = estimated_value / tx_count if tx_count > 0 else 0
        estimated_large = int(tx_count * 0.01)  # ~1% of transactions are large

        # Estimate net flow direction from mempool/transaction patterns
        trade_volume = data.get("trade_volume_usd", 0)
        miners_revenue = data.get("miners_revenue_usd", 0)

        # If miners are sending more than usual, it's exchange inflow
        net_flow = "neutral"
        if trade_volume > 0 and miners_revenue > 0:
            ratio = miners_revenue / trade_volume
            if ratio > 0.05:
                net_flow = "inflow"
            elif ratio < 0.02:
                net_flow = "outflow"

        return WhaleActivity(
            large_txns_24h=estimated_large,
            net_exchange_flow=net_flow,
            notable_txns=[{
                "estimated_daily_volume_usd": round(estimated_value, 2),
                "total_transactions_24h": tx_count,
                "avg_transaction_usd": round(avg_tx_value, 2),
            }],
        )
    except Exception as e:
        logger.warning("Whale activity fetch failed: %s", e)
        return None


def compute_correlations(price_data: dict[str, pd.DataFrame], period_days: int = 30) -> CorrelationMatrix | None:
    """Compute rolling correlations between crypto and traditional assets.

    Correlation measures how closely two assets move together (-1 to +1).

    What it means:
    - +1.0: Perfect positive correlation (move together exactly)
    - 0.0: No correlation (independent movement)
    - -1.0: Perfect negative correlation (move in opposite directions)

    Key correlations for crypto:
    - BTC-ETH: Usually 0.80-0.95 (very correlated)
    - BTC-SPY: Varies 0.2-0.7 (crypto follows stocks during risk events)
    - BTC-Gold: Usually -0.1 to 0.3 (weak, crypto isn't "digital gold" yet)
    - BTC-DXY: Usually -0.3 to -0.6 (strong dollar = weak crypto)

    Trading implications:
    - High BTC-SPY correlation: Crypto is trading as a risk asset
    - Low BTC-SPY correlation: Crypto has its own narrative
    - If you hold both BTC and ETH, you're NOT diversified (too correlated)
    """
    if not price_data or len(price_data) < 2:
        return None

    try:
        # Build a DataFrame of close prices
        close_prices = {}
        for ticker, df in price_data.items():
            if df is not None and len(df) >= period_days:
                cols = [c for c in df.columns if c.lower() == "close"]
                if cols:
                    series = df[cols[0]].tail(period_days).pct_change().dropna()
                    if len(series) >= period_days - 5:
                        close_prices[ticker] = series.values[:period_days - 1]

        if len(close_prices) < 2:
            return None

        # Find minimum common length
        min_len = min(len(v) for v in close_prices.values())
        aligned = {k: v[:min_len] for k, v in close_prices.items()}

        prices_df = pd.DataFrame(aligned)
        corr_matrix = prices_df.corr()

        pairs = {}
        tickers = list(corr_matrix.columns)
        for i, t1 in enumerate(tickers):
            for t2 in tickers[i + 1:]:
                pairs[f"{t1}-{t2}"] = round(corr_matrix.loc[t1, t2], 3)

        return CorrelationMatrix(pairs=pairs, period_days=period_days)
    except Exception as e:
        logger.warning("Correlation computation failed: %s", e)
        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main Intelligence Gatherer
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class CryptoDataCollector:
    """Collects all crypto intelligence across tiers.

    Usage:
        collector = CryptoDataCollector()
        intel = collector.collect_all()

        # Or collect specific tiers
        intel = collector.collect_tier1()
    """

    def collect_tier1(self) -> CryptoIntelligence:
        """Collect Tier 1 data: Fear & Greed, Dominance, Funding, OI."""
        logger.info("Collecting crypto Tier 1 data...")
        intel = CryptoIntelligence(timestamp=datetime.now().isoformat())

        intel.fear_greed = fetch_fear_greed()
        intel.dominance = fetch_dominance()
        intel.btc_funding = fetch_funding_rate("BTCUSDT")
        intel.eth_funding = fetch_funding_rate("ETHUSDT")
        intel.btc_open_interest = fetch_open_interest("BTCUSDT")
        intel.eth_open_interest = fetch_open_interest("ETHUSDT")

        logger.info("Tier 1 complete: F&G=%s, BTC dom=%.1f%%",
                     intel.fear_greed.value if intel.fear_greed else "N/A",
                     intel.dominance.btc_dominance if intel.dominance else 0)
        return intel

    def collect_tier2(self, intel: CryptoIntelligence | None = None) -> CryptoIntelligence:
        """Collect Tier 2 data: Stablecoin supply, Hash rate, Liquidation estimates."""
        logger.info("Collecting crypto Tier 2 data...")
        if intel is None:
            intel = CryptoIntelligence(timestamp=datetime.now().isoformat())

        intel.stablecoin_supply = fetch_stablecoin_supply()
        intel.hash_rate = fetch_hash_rate()
        intel.liquidation_estimate = estimate_liquidation_levels("BTCUSDT")

        logger.info("Tier 2 complete: stablecoin cap=$%.0fB, hash rate=%s TH/s",
                     (intel.stablecoin_supply.total_stablecoin_cap / 1e9) if intel.stablecoin_supply else 0,
                     intel.hash_rate.hash_rate if intel.hash_rate else "N/A")
        return intel

    def collect_tier3(
        self, intel: CryptoIntelligence | None = None,
        price_data: dict[str, pd.DataFrame] | None = None,
    ) -> CryptoIntelligence:
        """Collect Tier 3 data: DeFi, Gas, Whales, Correlations."""
        logger.info("Collecting crypto Tier 3 data...")
        if intel is None:
            intel = CryptoIntelligence(timestamp=datetime.now().isoformat())

        intel.defi = fetch_defi_snapshot()
        intel.gas = fetch_gas_data()
        intel.whale_activity = fetch_whale_activity()

        if price_data:
            intel.correlations = compute_correlations(price_data)

        logger.info("Tier 3 complete: DeFi TVL=$%.0fB, gas=%.3f gwei",
                     (intel.defi.total_tvl / 1e9) if intel.defi else 0,
                     intel.gas.gas_price_gwei if intel.gas else 0)
        return intel

    def collect_all(self, price_data: dict[str, pd.DataFrame] | None = None) -> CryptoIntelligence:
        """Collect all tiers of crypto intelligence."""
        intel = self.collect_tier1()
        self.collect_tier2(intel)
        self.collect_tier3(intel, price_data)
        return intel

    def to_dict(self, intel: CryptoIntelligence) -> dict:
        """Convert intelligence to a JSON-serializable dict."""
        from dataclasses import asdict
        result = {}

        if intel.fear_greed:
            result["fear_greed"] = asdict(intel.fear_greed)
        if intel.dominance:
            result["dominance"] = asdict(intel.dominance)
        if intel.btc_funding:
            result["btc_funding"] = asdict(intel.btc_funding)
        if intel.eth_funding:
            result["eth_funding"] = asdict(intel.eth_funding)
        if intel.btc_open_interest:
            result["btc_open_interest"] = asdict(intel.btc_open_interest)
        if intel.eth_open_interest:
            result["eth_open_interest"] = asdict(intel.eth_open_interest)
        if intel.stablecoin_supply:
            result["stablecoin_supply"] = asdict(intel.stablecoin_supply)
        if intel.hash_rate:
            result["hash_rate"] = asdict(intel.hash_rate)
        if intel.liquidation_estimate:
            result["liquidation_estimate"] = intel.liquidation_estimate
        if intel.defi:
            result["defi"] = asdict(intel.defi)
        if intel.gas:
            result["gas"] = asdict(intel.gas)
        if intel.whale_activity:
            result["whale_activity"] = asdict(intel.whale_activity)
        if intel.correlations:
            result["correlations"] = asdict(intel.correlations)

        result["timestamp"] = intel.timestamp
        return result

    def format_summary(self, intel: CryptoIntelligence) -> str:
        """Format a human-readable crypto intelligence summary."""
        lines = ["## Crypto Intelligence Report", ""]

        # Tier 1
        lines.append("### Tier 1: Core Metrics")
        if intel.fear_greed:
            fg = intel.fear_greed
            trend = ""
            if fg.history_7d:
                avg_7d = sum(fg.history_7d) / len(fg.history_7d)
                if fg.value > avg_7d + 5:
                    trend = " (trending greedier)"
                elif fg.value < avg_7d - 5:
                    trend = " (trending more fearful)"
            lines.append(f"- **Fear & Greed:** {fg.value}/100 — {fg.classification}{trend}")

        if intel.dominance:
            d = intel.dominance
            lines.append(f"- **BTC Dominance:** {d.btc_dominance:.1f}% | ETH: {d.eth_dominance:.1f}%")
            lines.append(f"- **Total Crypto Market Cap:** ${d.total_market_cap / 1e9:,.1f}B")

        if intel.btc_funding:
            f = intel.btc_funding
            lines.append(f"- **BTC Funding Rate:** {f.rate:.4%} ({f.direction}, annualized: {f.annualized:.1f}%)")

        if intel.eth_funding:
            f = intel.eth_funding
            lines.append(f"- **ETH Funding Rate:** {f.rate:.4%} ({f.direction}, annualized: {f.annualized:.1f}%)")

        if intel.btc_open_interest:
            oi = intel.btc_open_interest
            lines.append(f"- **BTC Open Interest:** ${oi.open_interest_usd / 1e9:,.2f}B ({oi.change_24h_pct:+.1f}% 24h)")

        if intel.eth_open_interest:
            oi = intel.eth_open_interest
            lines.append(f"- **ETH Open Interest:** ${oi.open_interest_usd / 1e9:,.2f}B ({oi.change_24h_pct:+.1f}% 24h)")

        # Tier 2
        lines.append("")
        lines.append("### Tier 2: Advanced Metrics")
        if intel.stablecoin_supply:
            s = intel.stablecoin_supply
            lines.append(f"- **Stablecoin Supply:** ${s.total_stablecoin_cap / 1e9:,.1f}B (USDT dominance: {s.usdt_dominance:.1f}%)")

        if intel.hash_rate:
            h = intel.hash_rate
            lines.append(f"- **BTC Hash Rate:** {h.hash_rate:,.1f} TH/s | Block: {h.block_height:,}")

        if intel.liquidation_estimate:
            liq = intel.liquidation_estimate
            lines.append(f"- **Liquidation Risk:** {liq.get('risk_level', 'unknown')} | Bias: {liq.get('bias', 'unknown')}")

        # Tier 3
        lines.append("")
        lines.append("### Tier 3: Ecosystem Intelligence")
        if intel.defi:
            d = intel.defi
            lines.append(f"- **DeFi TVL:** ${d.total_tvl / 1e9:,.1f}B | ETH TVL: ${d.eth_tvl / 1e9:,.1f}B")
            if d.top_protocols:
                top = d.top_protocols[0]
                lines.append(f"- **Top Protocol:** {top['name']} (${top['tvl'] / 1e9:,.1f}B, {top['change_1d']:+.1f}% 1d)")

        if intel.gas:
            g = intel.gas
            # Use dynamic precision — show more decimals when gas is very low
            fmt = ".1f" if g.gas_price_gwei >= 1 else ".3f"
            lines.append(f"- **ETH Gas:** {g.gas_price_gwei:{fmt}} Gwei (base: {g.base_fee_gwei:{fmt}}, tip: {g.priority_fee_gwei:{fmt}})")

        if intel.whale_activity:
            w = intel.whale_activity
            lines.append(f"- **Whale Activity:** ~{w.large_txns_24h} large txns | Net flow: {w.net_exchange_flow}")

        if intel.correlations:
            c = intel.correlations
            lines.append(f"- **Correlations ({c.period_days}d):**")
            for pair, corr in sorted(c.pairs.items()):
                strength = "strong" if abs(corr) > 0.7 else "moderate" if abs(corr) > 0.4 else "weak"
                lines.append(f"  - {pair}: {corr:+.3f} ({strength})")

        return "\n".join(lines)
