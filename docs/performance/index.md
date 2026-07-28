# 性能与可观测性

性能不是一个分数，而是系统在给定工作负载、资源与正确性约束下的行为。可靠的方法从问题与实验开始，用 profile 定位工作，用 metrics/logs/traces 解释运行，再用容量模型和故障树把局部证据连成系统因果。

## 阅读地图

- [基准设计](benchmarking.md)：从假设、工作负载和统计不确定性建立可重复测量。
- [采样、perf 与 eBPF](profiling.md)：区分计数、采样、插桩和追踪，解释 PMU、火焰图与内核观测。
- [指标、日志、追踪与连续剖析](observability.md)：设计可关联、可行动且成本受控的遥测。
- [容量与系统化排障](capacity-troubleshooting.md)：用 Little’s Law、排队、瓶颈与时间线形成闭环。

## 先问单位

看到“性能提升 20%”时，先追问：

- latency 还是 throughput？
- wall time、CPU time 还是 service time？
- 平均值、分位数还是最大值？
- bytes/s、requests/s、operations/core 还是能耗/operation？
- 单用户、固定并发还是固定到达率？
- 正确性、超时和丢弃是否一致？
- 测量持续多久，系统是否已进入稳态？

没有单位、负载与边界的数字不能支持工程决策。

## 证据阶梯

```text
symptom / SLO impact
  -> workload and queue state
  -> resource saturation
  -> profile / trace localization
  -> code, runtime, kernel, hardware mechanism
  -> controlled change
  -> before/after with rollback criteria
```

跳过中间层直接改代码，常会优化非瓶颈；只看 dashboard 不下钻机制，则难以解释反直觉变化。

## Reference

- [Linux `perf_event_open(2)`](https://man7.org/linux/man-pages/man2/perf_event_open.2.html)
- [Linux kernel: eBPF verifier](https://docs.kernel.org/bpf/verifier.html)
- [OpenTelemetry Specifications](https://opentelemetry.io/docs/specs/)
- [Google Benchmark User Guide](https://github.com/google/benchmark/blob/main/docs/user_guide.md)
- [Little: A Proof for the Queuing Formula $L=\lambda W$](https://doi.org/10.1287/opre.9.3.383)
