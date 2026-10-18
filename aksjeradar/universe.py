"""
Setter sammen aksjeuniverset: listene i config.yaml pluss (valgfritt) hele S&P 500.

S&P 500-listen hentes fra Wikipedia ved hver kjøring og lagres i databasen,
slik at en feil hos Wikipedia ikke stopper kjøringen – da brukes forrige liste,
og i verste fall en innebygd reserveliste med de største selskapene.
"""
from __future__ import annotations

import io
import logging

import requests

from .storage import Storage

log = logging.getLogger("aksjeradar.universe")

WIKI_SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

# Reserveliste hvis Wikipedia ikke svarer og databasen er tom
SP500_FALLBACK = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "GOOG", "META", "TSLA", "BRK-B", "AVGO", "JPM", "LLY", "V", "UNH",
    "XOM", "MA", "COST", "HD", "PG", "JNJ", "WMT", "NFLX", "ABBV", "BAC", "CRM", "ORCL", "CVX", "KO", "MRK",
    "AMD", "PEP", "CSCO", "TMO", "ACN", "LIN", "MCD", "ADBE", "ABT", "WFC", "PM", "GE", "IBM", "TXN", "CAT",
    "ISRG", "QCOM", "INTU", "DIS", "GS", "VZ", "AMGN", "BKNG", "NOW", "SPGI", "MS", "AXP", "T", "RTX", "NEE",
    "PFE", "UBER", "PGR", "LOW", "HON", "AMAT", "UNP", "BLK", "ETN", "SYK", "TJX", "COP", "SCHW", "ADP",
    "BSX", "C", "PANW", "ANET", "VRTX", "MU", "LRCX", "FI", "BMY", "GILD", "ADI", "DE", "MDT", "TMUS", "SBUX",
    "KLAC", "MMC", "PLTR", "CB", "PLD", "LMT", "MO", "SO", "INTC", "BA", "ELV", "DUK", "ICE", "REGN", "SHW",
    "WM", "CI", "AON", "EQIX", "APH", "CME", "PH", "TT", "MDLZ", "KKR", "ZTS", "CL", "CTAS", "PYPL", "SNPS",
    "CDNS", "ITW", "GD", "MCK", "USB", "EMR", "PNC", "NOC", "ORLY", "CMG", "MAR", "WELL", "ECL", "FDX",
    "CSX", "TGT", "MSI", "AJG", "ROP", "CARR", "APD", "TDG", "BDX", "AZO", "NSC", "ADSK", "HLT", "COF",
    "FTNT", "TFC", "SLB", "ABNB", "PSA", "SPG", "AFL", "ROST", "NXPI", "DHI", "TRV", "ALL", "MET", "AEP",
    "GM", "F", "PCAR", "SRE", "D", "O", "CCI", "KMB", "MNST", "AIG", "HUM", "PRU", "DLR", "CPRT", "FAST",
    "PAYX", "ODFL", "KMI", "OKE", "WMB", "LHX", "GWW", "AME", "EW", "IDXX", "A", "DXCM", "KDP", "HSY",
    "KHC", "GIS", "SYY", "STZ", "EL", "EA", "TTWO", "WBD", "CMCSA", "CHTR", "DASH", "CRWD", "DDOG", "WDAY",
    "TEAM", "ZS", "MRVL", "ON", "MCHP", "SMCI", "DELL", "HPQ", "HPE", "STX", "WDC", "GLW", "CTSH", "IT",
    "ACGL", "ARE", "AVB", "EQR", "VTR", "EXR", "VICI", "IRM", "SBAC", "AMT", "CEG", "VST", "NRG", "EXC",
    "XEL", "ED", "PEG", "PCG", "EIX", "ETR", "WEC", "ES", "DTE", "AEE", "CNP", "CMS", "ATO", "NI",
    "OXY", "EOG", "PSX", "MPC", "VLO", "DVN", "FANG", "HAL", "BKR", "HES", "TRGP", "CTRA", "APA", "EQT",
    "NUE", "STLD", "FCX", "NEM", "DOW", "DD", "PPG", "CF", "MOS", "ALB", "CTVA", "VMC", "MLM", "IP", "PKG",
    "AMCR", "BALL", "AVY", "LYB", "EMN", "CE", "IFF", "FMC", "URI", "PWR", "JCI", "CMI", "OTIS", "ROK",
    "DOV", "XYL", "FTV", "IR", "HUBB", "SNA", "SWK", "PNR", "NDSN", "AOS", "MAS", "LII", "WAB", "TXT", "HWM",
    "HII", "LDOS", "AXON", "BAH", "J", "EXPD", "CHRW", "JBHT", "LUV", "DAL", "UAL", "AAL", "NCLH", "RCL",
    "CCL", "MGM", "WYNN", "LVS", "CZR", "EXPE", "YUM", "DPZ", "DRI", "QSR", "NKE", "LULU", "TPR", "RL",
    "ULTA", "BBY", "DG", "DLTR", "KR", "WBA", "CVS", "MCK", "CAH", "COR", "HCA", "UHS", "DGX", "LH", "IQV",
    "ZBH", "BAX", "STE", "RMD", "ALGN", "COO", "HOLX", "TECH", "WAT", "MTD", "PKI", "BIIB", "MRNA", "INCY",
    "VRTX", "ILMN", "CRL", "BIO", "TFX", "PODD", "GEHC", "SOLV", "VLTO", "KVUE", "GEV", "SW", "DAY", "ERIE",
    "TKO", "APO", "WSM", "LEN", "PHM", "NVR", "TOL", "BLDR", "MHK", "WHR", "NWSA", "FOXA", "PARA", "OMC",
    "IPG", "LYV", "MTCH", "ETSY", "EBAY", "TSCO", "GPC", "AZO", "LKQ", "APTV", "BWA", "GRMN", "HAS", "POOL",
]


def fetch_sp500(store: Storage | None = None) -> list[str]:
    """Henter S&P 500-tickere fra Wikipedia. Faller tilbake til lagret liste, så til reservelisten."""
    try:
        import pandas as pd

        r = requests.get(WIKI_SP500, timeout=30, headers={"User-Agent": "Mozilla/5.0 (aksjeradar; personal research tool)"})
        r.raise_for_status()
        tables = pd.read_html(io.StringIO(r.text))
        table = next(t for t in tables if "Symbol" in t.columns)
        tickers = [str(s).strip().upper().replace(".", "-") for s in table["Symbol"].tolist()]
        tickers = [t for t in tickers if t and t != "NAN"]
        if len(tickers) >= 400:
            if store is not None:
                store.save_snapshot("universe", "sp500", {"tickers": tickers})
            log.info("S&P 500: %d tickere fra Wikipedia", len(tickers))
            return tickers
        log.warning("S&P 500-listen fra Wikipedia så for kort ut (%d) – bruker reserve", len(tickers))
    except Exception as e:  # noqa: BLE001
        log.warning("Kunne ikke hente S&P 500 fra Wikipedia: %s", e)
    if store is not None:
        payload, _ = store.load_snapshot("universe", "sp500")
        if payload and payload.get("tickers"):
            log.info("S&P 500: bruker lagret liste (%d)", len(payload["tickers"]))
            return list(payload["tickers"])
    log.info("S&P 500: bruker innebygd reserveliste (%d)", len(SP500_FALLBACK))
    return list(SP500_FALLBACK)


def build_universe(cfg: dict, store: Storage | None = None) -> list[str]:
    """Alle tickere: config-listene + S&P 500 (hvis slått på). Uten duplikater, i stabil rekkefølge."""
    from .config import all_tickers

    tickers = all_tickers(cfg)
    extra = cfg.get("universe_extra") or {}
    if extra.get("sp500"):
        tickers += fetch_sp500(store)
    seen: set[str] = set()
    out: list[str] = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out
