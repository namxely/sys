# 基准设计：让数字回答一个问题

基准不是“把代码跑很多次再取平均”，而是一项受控实验。它必须先定义要回答的问题、保持哪些条件相同、允许哪些变化、怎样验证结果仍正确，以及多大差异才具有工程意义。

## 从假设开始 {#hypothesis}

一个可证伪假设应写成：

> 在固定输入分布、并发度和机器配置下，变更 B 相对 A 将 p99 响应时间降低至少 10%，吞吐与错误率不退化超过 1%，峰值 RSS 不增加超过 5%。

它同时定义：

- independent variable：A/B 实现；
- controlled variables：输入、机器、compiler、资源；
- response variables：p99、throughput、errors、RSS；
- practical threshold：何种差异值得发布。

“新版本更快吗”缺少这些边界，任何单一数字都可能被挑选来回答。

## 选择基准层级 {#levels}

| 层级 | 适合回答 | 容易遗漏 |
| --- | --- | --- |
| microbenchmark | 单个函数/数据结构/指令序列成本 | cache 状态、优化消除、端到端交互 |
| component | runtime、存储引擎、协议栈局部 | 上下游排队与真实数据 |
| end-to-end | 用户可见 latency/throughput | 根因定位、实验成本 |
| production experiment | 真实分布与依赖 | 噪声、风险、因果混杂 |

正确策略往往是双向：end-to-end 发现真实退化，profile 定位到 component，再用 microbenchmark 快速迭代，最后回到端到端验证。

## 工作负载是基准的一部分 {#workload}

输入至少描述：

- size、shape、key/value 分布；
- hot/cold set 与复用距离；
- read/write/miss 比例；
- arrival process、burst 和 think time；
- request dependency 与 fan-out；
- error、timeout、cancel 比例；
- 数据压缩率、编码和对齐。

均匀随机常不是中立选择。真实系统可能是 Zipf 热点、长尾 object、周期 burst 或关联请求；这些形态改变 cache、锁、分支和 GC。

### Open loop 与 closed loop

closed-loop client 等前一个响应后再发请求；系统变慢时 client 自动降低到达率，可能隐藏过载。open-loop generator 按外部计划产生到达，可暴露 queue：

```text
closed: send -> wait response -> think -> send
open:   scheduled arrival ----> queue ----> service
```

两者回答不同问题。容量测试应报告 offered load 与 achieved throughput；发生 reject/drop 时不能只用成功请求 latency。

## 时间语义 {#time-semantics}

区分：

- wall-clock elapsed：包含等待、调度和 I/O；
- process/thread CPU time：执行消耗，不含多数等待；
- service time：真正被服务的时间；
- response time：queue + service + downstream；
- benchmark harness overhead：timer、loop、dispatch 与 serialization。

时钟要单调且精度足够；单次操作短于 timer resolution 时批量执行：

$$
\hat{t}_{op} = \frac{T_{\text{batch}} - T_{\text{harness}}}{N}
$$

但 subtract 两个相近 noisy 数会放大误差。更稳妥是增大 batch、对照空操作，并检查编译器没有把工作消除。

## 防止测到不存在的工作 {#optimization-barriers}

C++ microbenchmark：

```cpp
#include <benchmark/benchmark.h>
#include <vector>
static void BM_Sum(benchmark::State& state) {
    std::vector<int> xs(static_cast<size_t>(state.range(0)), 1);
    for (auto _ : state) {
        long long sum = 0;
        for (int x : xs) sum += x;
        benchmark::DoNotOptimize(sum);
        benchmark::ClobberMemory();
    }
    state.SetItemsProcessed(state.iterations() * state.range(0));
}
BENCHMARK(BM_Sum)->Range(64, 1 << 20);
BENCHMARK_MAIN();
```

`DoNotOptimize`/`ClobberMemory` 有精确语义和成本，不应随处添加。还要验证：

- 输出正确；
- 输入不会被 constant propagation 完全已知；
- setup 是否在 timed region 之外；
- allocator/cache 预热是否符合问题；
- benchmark 自身没有 data race；
- target compiler/flags 与生产一致。

## 热身与状态 {#warmup-state}

热身可能涉及：

- JIT compilation 与 tiering；
- page fault、dynamic linking；
- instruction/data cache；
- connection pool、DNS、TLS；
- allocator arena 与 GC；
- CPU frequency、thermal、power state；
- filesystem page cache。

“丢弃前 5 次”没有普适依据。画出时间序列，说明目标是 cold-start 还是 steady-state。若系统不平稳，单个总体均值会混合多个 regime。

实验之间可：

- 随机交错 A/B，降低温度与后台漂移；
- 在每轮前恢复明确状态；
- 记录而非假定频率、温度和 load；
- 对 cold benchmark 重启 process/VM；
- 对 steady-state 设稳定判据与最大热身时间。

Google Benchmark 支持 warmup、repetition、random interleaving、JSON context 与 performance counters；精确选项以使用版本的 user guide 为准。

## 延迟分布与 coordinated omission {#latency}

平均延迟无法表达尾部。至少报告请求计数、p50/p90/p95/p99/p99.9、最大值定义、timeout/drop 和 histogram 范围/精度。

coordinated omission 发生在测量源因系统变慢而停止生成本应到达的请求。例：目标每 10 ms 一次请求，某次服务暂停 1 s；若 client 等响应后才继续，只记录一个 1 s 样本，漏掉暂停期间约 99 个本应排队的高延迟请求。

修复需要按目标 arrival schedule 记录完整 response time，或用能校正预期间隔的 histogram。不能在结果后凭空补样本而忽略实际 admission/drop 策略。

### 分位数不确定性

样本 p99 是 order statistic；尾部有效样本数量约为 $0.01N$，例如 10,000 个请求只给 p99 以上约 100 个样本。自相关、burst 与不同 request class 还会降低有效样本量。

不要对分位数直接套普通均值的正态置信区间。可用：

- 独立 run 的分位数分布；
- block bootstrap 保留时间相关；
- histogram merge 前确认边界与单位一致；
- 按 request class 分层而不是混合 Simpson’s paradox。

## 重复、随机化与统计 {#statistics}

对独立 run 值 $x_i$：

$$
\bar{x} = \frac{1}{n}\sum_{i=1}^{n} x_i
$$

$$
s = \sqrt{\frac{1}{n-1}\sum_{i=1}^{n}(x_i-\bar{x})^2}
$$

但系统 benchmark 常不独立同分布：温度、邻居负载、缓存和版本 rollout 产生趋势。先画 run sequence，再考虑 mean/stddev。

报告：

- raw results 与 machine-readable context；
- median/mean 的选择理由；
- variability 与 confidence interval；
- effect size 和 practical threshold；
- outlier 处理规则在看数据前定义；
- multiple comparison 数量。

不能因 p-value 小就认为收益大，也不能因 CI 跨零就宣称“完全相同”。结果应是“在该环境和样本下未检测到超过阈值的差异”。

## 环境控制与披露 {#environment}

记录：

```text
CPU model/microcode, cores/SMT/NUMA
memory size/speed/topology
kernel/OS/container/cgroup
compiler/runtime/library + exact flags
governor/turbo/frequency/thermal
CPU affinity and interrupt placement
filesystem/storage/network
background load and security mitigations
source + dependency + config revisions
```

控制不是“把机器调到最快”，而是让比较可解释。关闭安全缓解、固定最大频率或清空 page cache 会改变问题，必须说明与生产差异。

SPEC CPU 的 run/reporting rules 把结果定义为观察，并要求披露影响性能的条件、验证输出和重复运行；这套思想比照搬某个 suite 分数更重要。

## 并发扩展测试 {#scaling}

对 concurrency $p$，同时记录：

- achieved throughput；
- latency distribution；
- utilization/saturation；
- errors/retries/drops；
- per-operation CPU/alloc/bytes；
- fairness 与 tenant skew。

画 $X(p)$ 不只找最高点，还找：

- linear region；
- contention 开始点；
- queueing knee；
- collapse/retry storm；
- capacity recovery hysteresis。

每个点要达到稳态并独立重复。只报告“64 线程最快”会掩盖 32→64 吞吐仅增 2% 而 p99 翻倍。

## 回归门禁 {#regression-gates}

性能 CI 容易不稳定。分层：

1. 每提交：短、确定的 algorithmic/work counters；
2. 定期 bare-metal：micro/component benchmark；
3. 预发布：端到端容量与 tail；
4. 生产 canary：真实 traffic 与 rollback。

用基线分布和 practical threshold，避免每次波动都阻塞；失败应保留 raw data、环境与 profile，允许重现，而不是“重跑到绿”。

## 常见失败 {#failure-modes}

- 没验证输出，优化器删掉了工作；
- setup、allocation 或 logging 混入 timed region；
- 用 debug build 比 production；
- A 总在 B 前运行，温度与 cache 混杂；
- 只测成功请求，忽略 timeout/drop；
- closed-loop 隐藏 overload；
- 只报均值或单次 p99；
- 不披露 compiler flags、CPU 和环境；
- microbenchmark 变快就推断系统变快；
- 多轮尝试只公布最好一次；
- benchmark framework overhead 大于被测操作；
- 根据观测结果再决定排除哪些 outlier。

## 继续阅读

- 找到时间花在哪里：见[采样、perf 与 eBPF](profiling.md)。
- 从 benchmark 到生产容量：见[容量与系统化排障](capacity-troubleshooting.md)。
- 保证 benchmark binary 可追溯：见[可复现构建](../tooling/build-reproducibility.md)。

## Reference

- [Google Benchmark User Guide](https://github.com/google/benchmark/blob/main/docs/user_guide.md)
- [SPEC CPU 2017 Run and Reporting Rules](https://www.spec.org/cpu2017/Docs/runrules.html)
- [HdrHistogram：Coordinated omission correction](https://hdrhistogram.github.io/HdrHistogram/JavaDoc/)
- [Little：A Proof for the Queuing Formula $L=\lambda W$](https://doi.org/10.1287/opre.9.3.383)
- [Kalibera and Jones：Rigorous Benchmarking in Reasonable Time](https://www.cl.cam.ac.uk/techreports/UCAM-CL-TR-892.pdf)
- [Georges, Buytaert and Eeckhout：Statistically Rigorous Java Performance Evaluation](https://doi.org/10.1145/1297027.1297033)
- [Linux `perf-stat(1)`](https://man7.org/linux/man-pages/man1/perf-stat.1.html)
