# 单压力测点调压阀预测维护示例

本示例构造 14 天、2 秒采样的管道出口压力数据。每个 process 周期严格为 40 秒（20 个采样点）。设备大部分时间处于 idle，压力围绕固定平台值运行；每天 process 数量和发生时刻随机变化，不采用完全均匀的周期。process 事件分别模拟图示的 Process 1（快速下降-低位保持-快速恢复）和 Process 2（V 形下降-渐进恢复）。

故障注入包括：Process 2 恢复变慢、Process 1 低位平台出现波纹、idle 稳定性恶化，以及 process 结束后 idle 压力 creep。另加入 Process 1 下降台阶幅值增大，以及 process 内波动周期缩短（单位时间波动次数增加）。

## 运行

```powershell
python .\pressure_regulator_demo\run_demo.py
```

输出位于 `pressure_regulator_demo/output/`：

- `pressure_readings.csv`：合成原始压力、idle/process 状态、Process 类型及事件标签
- `window_features.csv`：6 小时滑动窗口和状态感知特征
- `process_features.csv`：每个 40 秒 process 一行的事件级特征
- `frequency_test_summary.csv`：基于早期正常 process 的波动频率检测结果
- `synthetic_test_results.csv`：随机间隔、40 秒长度、幅值和频率退化的回归测试
- `feature_summary.csv`：故障前提前量统计
- `pressure_overview.png`：压力趋势与事件
- `feature_trends.png`：核心特征趋势

## 数据说明

数据是工程示例，不是真实设备记录。事件标签用于验证特征工程，不应用作真实阈值。压力平台、process 波形和故障强度均是可调参数。

## 公开数据参考

- LeakDB: https://www.epanet.informatik.uni-freiburg.de/leakdb
- BattLeDIM: https://www.battledim.org/
- Review and analysis of pipeline leak detection methods: https://doi.org/10.1016/j.jpse.2022.100074

这些公开数据主要是水网泄漏诊断，不能替代调压阀现场数据；它们适合验证压力瞬态、变化点和异常检测方法。
