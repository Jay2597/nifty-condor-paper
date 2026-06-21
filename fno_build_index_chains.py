"""fno_build_index_chains.py — download full NSE F&O bhavcopy for our dates and build liquid
option chains (settle+OI+vol) for BANKNIFTY / FINNIFTY / MIDCPNIFTY, so the NIFTY vol-seller
strategy can be revalidated on other indices on REAL prices.

Re-uses the same date set as chains_liq.json (entry + expiry days of the monthly cycles), which is
recoverable from the local NIFTY-only bhav filenames. Outputs data/fno/chains_liq_<SYM>.json with
rows [expiry, strike, type, settle, oi, vol]. Spot = UndrlygPric (new UDiFF) or the index daily
close (old format, BANKNIFTY only — it has a daily file).
"""
import csv, glob, io, json, os, time, urllib.request, zipfile

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fno")
SYMS = ["BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
       "Accept": "*/*"}


def d_old(s):
    dd, mm, yy = s.strip().upper().split("-")
    return f"{int(yy):04d}-{MON.index(mm)+1:02d}-{int(dd):02d}"


def fetch(url):
    raw = urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=40).read()
    z = zipfile.ZipFile(io.BytesIO(raw))
    return list(csv.DictReader(io.TextIOWrapper(z.open(z.namelist()[0]), encoding="utf-8-sig")))


def main():
    bnf_day = {r["date"][:10]: r["close"] for r in json.load(open(os.path.join(DATA, "BANKNIFTY_day.json")))}
    chains = {s: {} for s in SYMS}
    newd = sorted(os.path.basename(f)[3:11] for f in glob.glob(os.path.join(DATA, "bhav", "*.csv")))
    oldd = sorted(os.path.basename(f)[3:11] for f in glob.glob(os.path.join(DATA, "bhav_old", "*.csv")))
    fails = 0

    for i, ymd in enumerate(newd):
        url = f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip"
        try:
            rows = fetch(url)
        except Exception as e:
            fails += 1; print(f"  [new {ymd}] fail {type(e).__name__}"); continue
        for r in rows:
            if (r.get("OptnTp") or "").strip() not in ("CE", "PE"):
                continue
            sym = r.get("TckrSymb")
            if sym not in SYMS:
                continue
            try:
                dt = r["TradDt"][:10]; xp = r["XpryDt"][:10]; K = float(r["StrkPric"])
                settle = float(r["SttlmPric"]); oi = float(r["OpnIntrst"] or 0)
                vol = float(r["TtlTradgVol"] or 0); spot = float(r["UndrlygPric"] or 0)
            except (KeyError, ValueError):
                continue
            rec = chains[sym].setdefault(dt, {"spot": spot, "opts": []})
            if spot and not rec["spot"]:
                rec["spot"] = spot
            rec["opts"].append([xp, K, r["OptnTp"].strip(), settle, oi, vol])
        if (i + 1) % 20 == 0:
            print(f"  new {i+1}/{len(newd)} done"); time.sleep(0.2)

    for i, ymd in enumerate(oldd):
        y, m, dd = ymd[:4], ymd[4:6], ymd[6:8]
        url = (f"https://nsearchives.nseindia.com/content/historical/DERIVATIVES/{y}/"
               f"{MON[int(m)-1]}/fo{dd}{MON[int(m)-1]}{y}bhav.csv.zip")
        try:
            rows = fetch(url)
        except Exception as e:
            fails += 1; print(f"  [old {ymd}] fail {type(e).__name__}"); continue
        for r in rows:
            if r.get("INSTRUMENT") != "OPTIDX" or r.get("SYMBOL") != "BANKNIFTY":
                continue
            try:
                dt = d_old(r["TIMESTAMP"]); xp = d_old(r["EXPIRY_DT"]); K = float(r["STRIKE_PR"])
                settle = float(r["SETTLE_PR"]); oi = float(r["OPEN_INT"] or 0); vol = float(r["CONTRACTS"] or 0)
            except (KeyError, ValueError):
                continue
            rec = chains["BANKNIFTY"].setdefault(dt, {"spot": bnf_day.get(dt, 0.0), "opts": []})
            rec["opts"].append([xp, K, r["OPTION_TYP"].strip(), settle, oi, vol])
        if (i + 1) % 20 == 0:
            print(f"  old {i+1}/{len(oldd)} done"); time.sleep(0.2)

    for sym in SYMS:
        out = os.path.join(DATA, f"chains_liq_{sym}.json")
        json.dump(chains[sym], open(out, "w"))
        ds = sorted(chains[sym])
        print(f"{sym}: {len(ds)} dates {ds[0] if ds else '-'}..{ds[-1] if ds else '-'} -> {os.path.basename(out)}")
    print(f"download failures: {fails}")


if __name__ == "__main__":
    main()
