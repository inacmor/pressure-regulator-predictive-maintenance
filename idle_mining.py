"""First-version idle waveform mining.

Input: CSV with timestamp,pressure_bar only.
Manual template entry: templates.json (time range or external waveform CSV).
"""
from pathlib import Path
import json
import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

DT = 2.0

def load_templates(path):
    p = Path(path)
    if not p.exists():
        p.write_text(json.dumps({"templates": [], "example": {
            "template_id": "idle_anomaly_001", "source": "time_range",
            "start": "2026-01-01T00:00:00", "end": "2026-01-01T00:01:00",
            "correlation_threshold": 0.85}}, ensure_ascii=False, indent=2), encoding="utf-8")
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("templates", [])

def features(x):
    x = np.asarray(x, dtype=float); d = np.diff(x)
    slope = np.polyfit(np.arange(len(x)), x, 1)[0] if len(x) > 1 else np.nan
    signs = np.sign(d)
    return {
        "mean_bar": np.mean(x), "std_bar": np.std(x), "mad_bar": np.median(np.abs(x-np.median(x))),
        "range_bar": np.ptp(x), "p05_bar": np.quantile(x,.05), "p95_bar": np.quantile(x,.95),
        "net_change_bar": x[-1]-x[0], "slope_bar_sample": slope,
        "max_rise_bar_sample": np.max(d) if len(d) else 0, "max_drop_bar_sample": np.min(d) if len(d) else 0,
        "diff_rms_bar": np.sqrt(np.mean(d*d)) if len(d) else 0,
        "turning_points": int(np.sum(signs[1:]*signs[:-1] < 0)) if len(signs)>1 else 0,
        "positive_fraction": float(np.mean(d>0)) if len(d) else 0,
    }

def idle_windows(df, window_s=40, step_s=10, process_delta=.12):
    w, step = max(4,int(window_s/DT)), max(1,int(step_s/DT)); p=df.pressure_bar.to_numpy(); base=float(np.median(p[:min(len(p),900)]))
    rows=[]; wave=[]
    for s in range(0,len(df)-w+1,step):
        x=p[s:s+w]; # windows far from process excursions are idle candidates
        if np.max(np.abs(x-base)) > process_delta: continue
        f=features(x); f.update(window_id=len(rows),start_idx=s,end_idx=s+w-1,start_time=df.timestamp.iloc[s],end_time=df.timestamp.iloc[s+w-1],duration_s=window_s,baseline_bar=base)
        f["idle_mode"] = "idle_rise" if f["net_change_bar"] > .025 and f["positive_fraction"] > .55 else "idle_flat"
        rows.append(f); wave.append(x)
    return pd.DataFrame(rows), np.asarray(wave)

def normalize(x):
    x=np.asarray(x,float); return (x-x.mean())/(x.std()+1e-12)

def template_waveform(t, raw):
    if t.get("source") == "time_range":
        return raw[(raw.timestamp >= pd.Timestamp(t["start"])) & (raw.timestamp <= pd.Timestamp(t["end"]))].pressure_bar.to_numpy()
    if t.get("source") == "waveform_csv":
        return pd.read_csv(t["path"])["pressure_bar"].to_numpy()
    return None

def find_template_matches(raw, templates, role=None):
    """Scan the full raw pressure stream with manually selected templates."""
    rows=[]
    for t in templates:
        if role and t.get("role", "idle_anomaly") != role: continue
        tid=t["template_id"]; threshold=float(t.get("correlation_threshold",.85)); q=template_waveform(t, raw)
        if q is None or len(q)<4: continue
        q=normalize(q)
        step=max(1,int(t.get("scan_step_s", DT)/DT)); n=len(q)
        for s in range(0,len(raw)-n+1,step):
            x=raw.pressure_bar.iloc[s:s+n].to_numpy()
            xx=normalize(np.interp(np.linspace(0,len(x)-1,len(q)),np.arange(len(x)),x)); corr=float(np.corrcoef(q,xx)[0,1])
            if corr>=threshold:
                r={"template_id":tid,"role":t.get("role","idle_anomaly"),"start_idx":s,"end_idx":s+n-1,
                   "start_time":raw.timestamp.iloc[s],"end_time":raw.timestamp.iloc[s+n-1],"similarity":corr,
                   "range_bar":float(np.ptp(x)),"duration_s":float((n-1)*DT)}; rows.append(r)
    if not rows: return pd.DataFrame(columns=["template_id","role","start_idx","end_idx","start_time","end_time","similarity","range_bar","duration_s"])
    out=pd.DataFrame(rows).sort_values(["start_idx","similarity"],ascending=[True,False])
    # Keep the best template match for overlapping windows.
    keep=[]; last_end=-1
    for _,r in out.iterrows():
        if int(r.start_idx)>last_end: keep.append(r); last_end=int(r.end_idx)
    return pd.DataFrame(keep)

def mask_intervals(n, matches, padding_s=4):
    mask=np.zeros(n,dtype=bool); pad=max(0,int(padding_s/DT))
    for _,r in matches.iterrows(): mask[max(0,int(r.start_idx)-pad):min(n,int(r.end_idx)+pad+1)]=True
    return mask

def match_templates(df, waves, templates, raw):
    """Backward-compatible idle-window matching wrapper."""
    matches=find_template_matches(raw, templates, role="idle_anomaly")
    if not len(matches): return matches
    return matches
    return pd.DataFrame(rows)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--input",default="output/pressure_readings.csv"); ap.add_argument("--out",default="output/idle_mining"); ap.add_argument("--templates",default="templates.json"); a=ap.parse_args()
    out=Path(a.out); out.mkdir(parents=True,exist_ok=True); raw=pd.read_csv(a.input,parse_dates=["timestamp"])
    templates=load_templates(a.templates)
    process_matches=find_template_matches(raw, templates, role="process")
    idle_matches=find_template_matches(raw, templates, role="idle_anomaly")
    process_matches.to_csv(out/"process_template_matches.csv",index=False)
    idle_matches.to_csv(out/"template_matches.csv",index=False)
    excluded=mask_intervals(len(raw), process_matches, padding_s=4)
    idle_raw=raw.loc[~excluded].reset_index(drop=True)
    f,w=idle_windows(idle_raw); f.to_csv(out/"idle_window_features.csv",index=False)
    for col in [c for c in f.columns if c.endswith("_bar") or c in ["turning_points","positive_fraction"]]:
        if col not in f: continue
        fig,ax=plt.subplots(figsize=(10,3)); ax.plot(f.start_time,f[col],lw=.7); ax.set_title(col); ax.grid(alpha=.2); fig.autofmt_xdate(); fig.tight_layout(); fig.savefig(out/f"feature_{col}.png",dpi=150); plt.close(fig)
    daily=f.assign(date=f.start_time.dt.date).groupby("date").agg(windows=("window_id","count"),mean_std=("std_bar","mean"),p95_range=("range_bar","quantile"),mean_diff_rms=("diff_rms_bar","mean"),rise_fraction=("idle_mode",lambda x:(x=="idle_rise").mean())).reset_index()
    daily.to_csv(out/"idle_daily_summary.csv",index=False)
    if len(idle_matches):
        m=idle_matches.assign(date=idle_matches.start_time.dt.date).groupby(["date","template_id"]).agg(matches=("similarity","count"),mean_similarity=("similarity","mean"),mean_amplitude=("range_bar","mean")).reset_index(); m.to_csv(out/"template_daily_summary.csv",index=False)
    print(f"process_matches={len(process_matches)} idle_windows={len(f)} idle_matches={len(idle_matches)} templates={len(templates)} output={out}")

if __name__ == "__main__": main()
