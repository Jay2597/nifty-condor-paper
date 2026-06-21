"""fno_build_liquid_chains.py — rebuild the NIFTY option chain WITH open-interest & volume.

The earlier chains.json kept only [expiry, strike, type, settle] and so could not distinguish a
liquid strike from an illiquid one whose settlement price is stale/theoretical (the artifact that
inflated the condor backtest — see [[fno-strategy]]). This re-parses the raw bhavcopy CSVs in
data/fno/bhav (new UDiFF) + data/fno/bhav_old (old format) and emits chains_liq.json:

    { "YYYY-MM-DD": { "spot": float,
                      "opts": [ [expiry, strike, "CE"/"PE", settle, oi, vol], ... ] }, ... }

spot = UndrlygPric (new format) or NIFTY50 daily close (old format, which has no underlying col).
"""
import csv, glob, json, os
from datetime import datetime

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fno")
MON = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def d_old(s):                       # '04-JUL-2023' or '06-Jul-2023' -> '2023-07-04'
    dd, mm, yy = s.strip().upper().split("-")
    return f"{int(yy):04d}-{MON[mm]:02d}-{int(dd):02d}"


def d_new(s):                       # already '2024-07-09'
    return s.strip()[:10]


def build():
    nifty = {r["date"][:10]: r["close"]
             for r in json.load(open(os.path.join(DATA, "NIFTY50_day.json")))}
    chains = {}

    # ---- old format ----
    for fp in glob.glob(os.path.join(DATA, "bhav_old", "*.csv")):
        with open(fp, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("INSTRUMENT") != "OPTIDX" or row.get("SYMBOL") != "NIFTY":
                    continue
                try:
                    dt = d_old(row["TIMESTAMP"]); xp = d_old(row["EXPIRY_DT"])
                    strike = float(row["STRIKE_PR"]); typ = row["OPTION_TYP"].strip()
                    settle = float(row["SETTLE_PR"]); oi = float(row["OPEN_INT"] or 0)
                    vol = float(row["CONTRACTS"] or 0)
                except (KeyError, ValueError):
                    continue
                rec = chains.setdefault(dt, {"spot": nifty.get(dt, 0.0), "opts": []})
                rec["opts"].append([xp, strike, typ, settle, oi, vol])

    # ---- new UDiFF format ----
    for fp in glob.glob(os.path.join(DATA, "bhav", "*.csv")):
        with open(fp, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("TckrSymb") != "NIFTY" or row.get("FinInstrmTp") != "IDO":
                    continue
                otp = (row.get("OptnTp") or "").strip()
                if otp not in ("CE", "PE"):
                    continue
                try:
                    dt = d_new(row["TradDt"]); xp = d_new(row["XpryDt"])
                    strike = float(row["StrkPric"]); settle = float(row["SttlmPric"])
                    oi = float(row["OpnIntrst"] or 0); vol = float(row["TtlTradgVol"] or 0)
                    spot = float(row["UndrlygPric"] or 0)
                except (KeyError, ValueError):
                    continue
                rec = chains.setdefault(dt, {"spot": spot or nifty.get(dt, 0.0), "opts": []})
                if spot and not rec["spot"]:
                    rec["spot"] = spot
                rec["opts"].append([xp, strike, typ if False else otp, settle, oi, vol])

    out = os.path.join(DATA, "chains_liq.json")
    json.dump(chains, open(out, "w"))
    dates = sorted(chains)
    print(f"built {out}: {len(dates)} dates {dates[0]}..{dates[-1]}")
    return chains


if __name__ == "__main__":
    build()
