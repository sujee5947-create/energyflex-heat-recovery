"""Convert raw ESIF CSVs (JS-style timestamps, irregular ~1-min samples) into hourly means.

Usage: python prep_esif.py <power.csv.zip> <weather.csv.zip> <out_dir>
Writes esif_hourly.csv with UTC hourly index. No values are modified except unit conversion °F→°C
(new column t_out_c) and removal of the 1969 placeholder rows (epoch 0 = missing).
"""
import sys
import zipfile
from pathlib import Path
import pandas as pd


def parse_ts(s):
    # "Mon Nov 09 2015 20:00:01 GMT-0700 (Mountain Standard Time)" -> aware datetime -> UTC
    core = s.str.replace(r"\s*\(.*\)$", "", regex=True).str.replace("GMT", "", regex=False)
    return pd.to_datetime(core, format="%a %b %d %Y %H:%M:%S %z", errors="coerce", utc=True)


def hourly(zpath, cols, chunksize=2_000_000):
    with zipfile.ZipFile(zpath) as z:
        name = next(n for n in z.namelist() if n.endswith(".csv") and not n.startswith("__MACOSX"))
        sums, counts, nrows, bad = None, None, 0, 0
        with z.open(name) as f:
            for ch in pd.read_csv(f, usecols=["ts"] + cols, chunksize=chunksize, low_memory=False):
                nrows += len(ch)
                ch["ts"] = parse_ts(ch["ts"])
                bad += ch["ts"].isna().sum()
                ch = ch.dropna(subset=["ts"])
                ch = ch[ch.ts.dt.year >= 2000]
                ch["h"] = ch.ts.dt.floor("h")
                g = ch.groupby("h")[cols]
                s, c = g.sum(min_count=1), g.count()
                sums = s if sums is None else sums.add(s, fill_value=0)
                counts = c if counts is None else counts.add(c, fill_value=0)
    out = sums / counts.where(counts > 0)
    out.attrs.update(rows=nrows, unparsed_ts=int(bad))
    return out, counts


if __name__ == "__main__":
    pz, wz, od = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    od.mkdir(parents=True, exist_ok=True)
    pcols = ["cooling_kw", "energy_reuse", "ere", "hvac_kw", "it_power_kw", "plug_and_light_kw", "pue", "pump_kw"]
    p, pc = hourly(pz, pcols)
    w, wc = hourly(wz, ["outdoor_air_temp", "outdoor_air_humidity"])
    w = w[(w.outdoor_air_temp != 0) | (w.outdoor_air_humidity != 0)]
    df = p.join(w, how="inner")
    df["t_out_c"] = (df.outdoor_air_temp - 32) * 5 / 9
    df["n_power_samples"] = pc["it_power_kw"]
    df.to_csv(od / "esif_hourly.csv", encoding="utf-8-sig")
    print("power rows", p.attrs, "weather rows", w.attrs)
    print("hourly rows", len(df), df.index.min(), df.index.max())
    print(df.describe().T.round(3).to_string())
