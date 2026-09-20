"""Pressure-only process simulation and self-contained HTML result report."""
from pathlib import Path
import base64
import io
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent / "output"
OUT.mkdir(exist_ok=True)
DT, DAYS, SEED = 2, 14, 42
START = pd.Timestamp("2025-01-01")
N = DAYS * 86400 // DT


def template(kind, depth=1.25):
    x = np.arange(20) * DT
    if kind == "process1":
        return np.interp(x, [0, 8, 30, 36, 40], [0, -depth, -depth, 0, 0])
    return np.interp(x, [0, 14, 40], [0, -1.10, 0])


def schedule(rng):
    events = []
    for day in range(DAYS):
        count = int(rng.integers(9, 17))
        # Ensure non-overlap and a different randomized daily spacing.
        slots = np.sort(rng.choice(np.arange(day*43200, (day+1)*43200-30, 60), count, replace=False))
        for start in slots:
            pid = len(events)
            events.append((pid, int(start), "process1" if pid % 2 == 0 else "process2"))
    return events


def simulate(mode="combined"):
    rng = np.random.default_rng(SEED)
    events = schedule(rng)
    days = np.arange(N) / 43200
    idle_noise = 0.012 + (0.045*np.clip((days-7)/7, 0, 1) if mode == "combined" else 0)
    pressure = 4 + rng.normal(0, idle_noise, N)
    pid_col = np.full(N, -1, dtype=np.int32)
    kind_col = np.full(N, "idle", dtype="<U8")
    for pid, start, kind in events:
        progress = np.clip((start/43200-7)/7, 0, 1)
        depth = 1.25 + (0.35*progress if mode == "combined" and kind == "process1" else 0)
        signal = template(kind, depth)
        if kind == "process1" and mode in ("combined", "frequency_only", "amplitude_only", "both"):
            ix = np.arange(5, 15)
            hz = 0.075 + (0.12*progress if mode in ("combined", "frequency_only", "both") else 0)
            amp = 0.075*(1+progress) if mode in ("combined", "amplitude_only", "both") else 0.075
            signal[ix] += amp*np.sin(2*np.pi*hz*ix*DT)
        pressure[start:start+20] += signal + rng.normal(0, .010, 20)
        pid_col[start:start+20] = pid
        kind_col[start:start+20] = kind
    if mode == "combined":
        m = (days >= 9) & (pid_col < 0)
        pressure[m] += 0.09*np.clip((days[m]-9)/5, 0, 1)*np.sin(np.arange(m.sum())/12)
    return pd.DataFrame({"timestamp": START + pd.to_timedelta(np.arange(N)*DT, unit="s"),
                         "pressure_bar": pressure, "state": np.where(pid_col < 0, "idle", "process"),
                         "process_type": kind_col, "process_id": pid_col})


def features(raw):
    rows = []
    for pid, g in raw[raw.process_id >= 0].groupby("process_id", sort=True):
        p = g.pressure_bar.to_numpy()
        if len(p) != 20:
            continue
        start, kind = g.timestamp.iloc[0], g.process_type.iloc[0]
        before = raw.iloc[max(0, g.index[0]-20):g.index[0]]
        idle = before.loc[before.state == "idle", "pressure_bar"]
        baseline = float(idle.median()) if len(idle) else 4.0
        residual = p-baseline-template(kind)
        middle = residual[5:15]
        middle = middle-np.polyval(np.polyfit(np.arange(10), middle, 1), np.arange(10))
        spec = np.abs(np.fft.rfft(middle*np.hanning(10)))**2
        hz = np.fft.rfftfreq(10, DT)
        high = float(spec[hz >= .15].sum())
        low = float(spec[(hz > 0) & (hz < .15)].sum())
        row = {"process_id": pid, "timestamp": start, "day": int((start-START).total_seconds()//86400),
               "process_type": kind, "duration_s": 40, "drop_amplitude_bar": baseline-p.min(),
               "high_low_energy_ratio": high/(low+1e-12), "middle_residual_std_bar": middle.std(),
               "dominant_hz": hz[1:][np.argmax(spec[1:])]}
        for name, sl in {"descent": slice(0,5), "hold_valley": slice(5,15), "recovery": slice(15,20)}.items():
            q = p[sl]; diff = np.diff(q); signs = np.sign(diff)
            row[f"{name}_slope_bar_s"] = (q[-1]-q[0])/((len(q)-1)*DT)
            row[f"{name}_range_bar"] = np.ptp(q)
            row[f"{name}_turning_points"] = int(np.sum(signs[1:]*signs[:-1] < 0))
        rows.append(row)
    return pd.DataFrame(rows)


def detect(pf):
    p1 = pf[pf.process_type == "process1"]
    threshold = float(p1[p1.day < 3].high_low_energy_ratio.quantile(.95))
    daily = p1.groupby("day").agg(events=("process_id", "count"),
                                   frequency=("high_low_energy_ratio", "median"),
                                   amplitude=("middle_residual_std_bar", "median"),
                                   drop=("drop_amplitude_bar", "median")).reset_index()
    daily["threshold"] = threshold
    daily["above"] = (daily.day >= 3) & (daily.frequency > threshold)
    daily["alert"] = daily.above.rolling(2, min_periods=2).sum().ge(2)
    for col in ("frequency", "amplitude", "drop"):
        daily[f"{col}_slope"] = daily[col].rolling(5, min_periods=5).apply(lambda y: np.polyfit(np.arange(len(y)), y, 1)[0], raw=True)
        daily[f"{col}_up_count"] = daily[col].diff().gt(0).rolling(5, min_periods=5).sum()
    daily["trend_alert"] = daily.frequency_slope.gt(0) & daily.amplitude_slope.gt(0) & daily.frequency_up_count.ge(3) & daily.amplitude_up_count.ge(3)
    return daily


def trend_summary(daily):
    specs = [("frequency", "Process 内波动频率/高频能量", "高频能量持续上升，需排查调节回路、阀芯颤振或气源脉动。"),
             ("amplitude", "Process 中段波动幅值", "保持段压力波动持续变大，说明稳定性变差，也可能受工艺负荷影响。"),
             ("drop", "Process 1 压降幅值", "同类 Process 1 压降逐渐变深，可能是调压能力、供气或下游负荷变化。")]
    tail = daily.tail(5); rows = []
    for key, name, meaning in specs:
        rows.append({"feature": key, "meaning": name, "slope_per_day": float(tail[f"{key}_slope"].iloc[-1]),
                     "increases_in_last_4": int(tail[f"{key}_up_count"].iloc[-1]),
                     "trend_alert": bool(key in ("frequency", "amplitude") and daily.trend_alert.iloc[-1]),
                     "engineering_interpretation": meaning})
    return pd.DataFrame(rows)


def test_scenarios():
    rows = []
    for mode in ("normal", "amplitude_only", "frequency_only", "both"):
        pf = features(simulate(mode))
        early = pf[(pf.day < 3) & (pf.process_type == "process1")]
        late = pf[(pf.day >= 11) & (pf.process_type == "process1")]
        rows.append({"scenario": mode, "events": len(pf),
                     "frequency_ratio": late.high_low_energy_ratio.median()/early.high_low_energy_ratio.median(),
                     "amplitude_ratio": late.middle_residual_std_bar.median()/early.middle_residual_std_bar.median()})
    result = pd.DataFrame(rows)
    by_mode = result.set_index("scenario")
    checks = {
        "normal": by_mode.loc["normal", "frequency_ratio"] < 3 and by_mode.loc["normal", "amplitude_ratio"] < 1.3,
        "amplitude_only": by_mode.loc["amplitude_only", "frequency_ratio"] < 3 and by_mode.loc["amplitude_only", "amplitude_ratio"] > 1.3,
        "frequency_only": by_mode.loc["frequency_only", "frequency_ratio"] > 3 and by_mode.loc["frequency_only", "amplitude_ratio"] < 1.3,
        "both": by_mode.loc["both", "frequency_ratio"] > 3 and by_mode.loc["both", "amplitude_ratio"] > 1.3,
    }
    result["passed"] = result.scenario.map(checks)
    return result


def png_data(fig):
    stream = io.BytesIO(); fig.savefig(stream, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return "data:image/png;base64,"+base64.b64encode(stream.getvalue()).decode("ascii")


def report(raw, pf, daily, tests, trends_df):
    early = pf[(pf.process_type == "process1") & (pf.day < 3)].iloc[0]
    late = pf[(pf.process_type == "process1") & (pf.day >= 11)].iloc[-1]
    fig, ax = plt.subplots(1,2,figsize=(10,3.5),sharey=True)
    for a, r, label in zip(ax, (early,late), ("Early Process 1","Late Process 1")):
        p = raw.loc[raw.process_id == r.process_id, "pressure_bar"].to_numpy()
        a.plot(np.arange(20)*2,p,"o-",markersize=3,color="#206f84")
        a.axvspan(10,30,color="#e6b35c",alpha=.22)
        a.set(title=label,xlabel="Seconds",ylabel="Pressure (bar)"); a.grid(alpha=.2)
    wave = png_data(fig)
    fig, ax = plt.subplots(3,1,figsize=(9,7),sharex=True)
    for a, key, label in zip(ax,("drop","amplitude","frequency"),("Drop (bar)","Middle residual SD (bar)","High/low energy ratio")):
        a.plot(daily.day+1,daily[key],"o-",color="#206f84"); a.set_ylabel(label); a.grid(alpha=.2)
    ax[-1].axhline(daily.threshold.iloc[0],color="#b44739",ls="--",label="Baseline P95")
    ax[-1].legend(); ax[-1].set_xlabel("Day")
    trends = png_data(fig)
    first = daily.loc[daily.alert,"day"].min()
    first_text = f"第 {int(first)+1} 天" if pd.notna(first) else "未触发"
    gaps = pf.timestamp.sort_values().diff().dropna().dt.total_seconds()
    tr = "".join(f"<tr><td>{r.scenario}</td><td>{r.events}</td><td>{r.frequency_ratio:.2f}×</td><td>{r.amplitude_ratio:.2f}×</td><td>{'通过' if r.passed else '未通过'}</td></tr>" for r in tests.itertuples())
    dr = "".join(f"<tr><td>{r.day+1}</td><td>{r.events}</td><td>{r.drop:.3f}</td><td>{r.amplitude:.4f}</td><td>{r.frequency:.2f}</td><td>{'告警' if r.alert else '—'}</td></tr>" for r in daily.itertuples())
    rr = "".join(f"<tr><td>{r.meaning}</td><td>{r.slope_per_day:.5f}</td><td>{r.increases_in_last_4}/4</td><td>{'趋势告警' if r.trend_alert else '—'}</td><td>{r.engineering_interpretation}</td></tr>" for r in trends_df.itertuples())
    html = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>压力数据检测测试报告</title><style>
body{{margin:0;background:#f5f7f6;color:#1d3037;font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif}}main{{max-width:980px;margin:auto;padding:25px 18px 70px}}h1{{line-height:1.3}}h2{{margin-top:40px;padding-top:16px;border-top:1px solid #ccd8d8}}p{{max-width:78ch}}.lead{{font-size:1.12em}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.card,figure,table{{background:white;border:1px solid #d8e2e1;border-radius:8px}}.card{{padding:12px}}.card strong{{display:block;font-size:1.35em;color:#206f84}}.card span,figcaption,.muted{{color:#53666d}}figure{{margin:18px 0;padding:12px}}img{{width:100%;height:auto}}figcaption{{font-size:.9em}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%}}th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid #dce5e4;white-space:nowrap}}th{{background:#e7eeee}}.warning{{border-left:4px solid #b44739;background:#fff4ef;padding:10px 16px}}@media(max-width:650px){{.cards{{grid-template-columns:repeat(2,1fr)}}h1{{font-size:1.5em}}figure{{padding:4px}}}}
</style></head><body><main><h1>单压力测点：14 天合成数据测试报告</h1><p class="lead">结论：合成数据中 Process 1 压降和保持段波动逐渐增强。基于频率能量比的连续告警首次出现于<strong>{first_text}</strong>。这是方法演示，不代表真实阀门故障识别能力。</p>
<div class="cards"><div class="card"><strong>{len(raw):,}</strong><span>2 秒采样点</span></div><div class="card"><strong>{len(pf)}</strong><span>40 秒 process</span></div><div class="card"><strong>{pf.groupby('day').size().min()}–{pf.groupby('day').size().max()}</strong><span>每天 process 数</span></div><div class="card"><strong>{gaps.min():.0f}–{gaps.max():.0f}s</strong><span>相邻起始间隔</span></div></div>
<h2>1. 数据构造和波形</h2><p>Idle 压力约为 4 bar。Process 1 快速下降、低位保持、快速恢复；Process 2 呈 V 形。两类事件混合且每天发生时间不均匀。以下黄色区域为 Process 1 中段，后期故意叠加更深的压降、更大的波动幅值和更快的波动。</p><figure><img src="{wave}" alt="早期和后期Process 1压力波形"><figcaption>40 秒内有 20 个采样点；此图比较实际生成的一次早期和一次后期事件。</figcaption></figure>
<h2>2. 提取特征和检测规则</h2><p>每个事件单独分为下降（0–8 秒）、保持/谷值（10–28 秒）、恢复（30–38 秒），分别计算斜率、范围和转折点。压降由事件前 idle 压力中位数减去事件最低值。频率指标先扣除正常 Process 1 模板并去线性趋势，再对中段 10 个点计算高频（≥0.15 Hz）与低频（0–0.15 Hz）能量比。前 3 天同类事件的第 95 百分位为阈值；第 4 天起，连续两天日中位数超阈才告警。</p><figure><img src="{trends}" alt="每日压降、波动幅值和高低频能量比趋势"><figcaption>红色虚线是早期正常事件的频率指标阈值，仅对应第三幅图。</figcaption></figure><div class="scroll"><table><thead><tr><th>天</th><th>Process 1数</th><th>压降 bar</th><th>中段标准差 bar</th><th>高低频能量比</th><th>检测</th></tr></thead><tbody>{dr}</tbody></table></div>
<h2>3. 对照场景测试</h2><p>四组使用同一随机种子和同一事件时间表，仅改变过程内注入波动：正常、只增幅、只增频、幅频均增。下表是末 3 天与前 3 天同类事件中位数之比。预设判据：频率变化比值 &gt;3，幅值变化比值 &gt;1.3；未注入相应变化的指标应低于其阈值。正常组频率比约 2，说明短序列仍有随机波动，不能把单个比值略大于 1 当成故障。</p><div class="scroll"><table><thead><tr><th>场景</th><th>事件数</th><th>频率能量比</th><th>残差幅值</th><th>判据</th></tr></thead><tbody>{tr}</tbody></table></div>
<h2>4. 局限与下一步</h2><p class="warning">仅凭压力无法把压降变大归因于阀门；工艺负荷和供气变化也可能造成同样波形。2 秒采样的奈奎斯特频率是 0.25 Hz，中段只有 10 点，频率分辨率 0.05 Hz；高低频能量比不是准确的机械振动频率。现场需更高采样率、工艺配方分层、维护记录及真实正常基线。</p><p class="muted">生成参数：固定随机种子 {SEED}，14 天、2 秒采样、每个 process 40 秒。数据与报告均为本地合成，HTML 图片内嵌，离线可打开。CSV 可用于独立复核。</p></main></body></html>'''
    trend_block = f'<h2>4. 大方向趋势检测</h2><p>最近 5 天斜率与连续上升次数用于识别持续恶化，而不是单次异常。频率和幅值同时持续上升时才标记趋势告警。</p><div class="scroll"><table><tr><th>指标</th><th>每日斜率</th><th>最近4次上升</th><th>判断</th><th>实际意义</th></tr>{rr}</table></div>'
    html = html.replace('<h2>4. 局限与下一步</h2>', trend_block + '<h2>5. 局限与下一步</h2>')
    (OUT/"report.html").write_text(html,encoding="utf-8")


def main():
    raw = simulate("combined")
    pf = features(raw)
    daily = detect(pf)
    trends_df = trend_summary(daily)
    tests = test_scenarios()
    assert len(raw) == N and pf.duration_s.eq(40).all()
    assert pf.groupby("day").size().nunique() > 1
    assert tests.passed.all(), tests.to_string(index=False)
    raw.to_csv(OUT/"pressure_readings.csv",index=False)
    pf.to_csv(OUT/"process_features.csv",index=False)
    daily.to_csv(OUT/"daily_detection.csv",index=False)
    tests.to_csv(OUT/"scenario_tests.csv",index=False)
    trends_df.to_csv(OUT/"trend_summary.csv", index=False)
    report(raw,pf,daily,tests,trends_df)
    print(f"samples={len(raw)} processes={len(pf)} report={OUT/'report.html'}")
    print(tests.to_string(index=False))
    print(daily[['day','frequency','alert']].to_string(index=False))


if __name__ == "__main__":
    main()
