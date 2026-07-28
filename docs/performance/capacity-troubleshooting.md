# 容量、排队与系统化排障

性能问题不是一个数字，而是需求、资源、调度与反馈回路共同形成的状态。延迟升高可能来自服务时间变长，也可能只是排队；CPU 未满可能因为 lock、I/O、限额或下游；吞吐不再增长可能是合理背压，也可能是请求在入口前已经被丢弃。

本页建立一套从 workload 到 queue、从 saturation 到证据的推理框架。公式是模型，不是对生产系统的自动证明；每次应用都要写清稳态、独立性、服务纪律与测量边界。

## 先定义工作与边界 {#workload}

容量问题至少需要这些量：

| 符号 | 含义 |
| --- | --- |
| $\lambda$ | 到达率，单位 work/time |
| $X$ | 完成吞吐 |
| $S$ | 单个 work 的 service time |
| $R$ | response time，含等待与服务 |
| $N$ | 系统内平均并发 work |
| $m$ | 并行 server 数 |
| $\rho$ | server utilization |

“request”必须有稳定边界。一次用户操作可能产生多个 HTTP attempt、cache miss、database query 和 queue message；若入口以 operation 计、下游以 attempt 计，两个 QPS 不能直接相减。

还要区分：

- **offered load**：调用方想送入多少；
- **admitted load**：入口接受多少；
- **completed throughput**：成功或终止多少；
- **goodput**：满足正确性与 SLO 的有效结果；
- **rejected/dropped**：被 admission、queue 或 transport 丢弃多少。

系统过载时 completed throughput 可能看似稳定，只因更多请求在观测点之前被拒绝。

## Little 定律：把并发、吞吐和停留时间连起来 {#little}

对长期稳定、边界一致且无 work 隐式消失的系统：

$$
N = \lambda R
$$

例如稳定完成 2,000 request/s、平均 response time 40 ms：

$$
N = 2000 \times 0.04 = 80
$$

这意味着平均约 80 个请求在该边界内，不代表必须开 80 个线程：async runtime 可让一个 thread 持有许多等待中的 request，CPU-bound worker 则通常需要接近可运行并行度的线程。

Little 定律也适用于 queue：

$$
N_q = \lambda W_q
$$

前提是 arrival、departure 和 residence time 来自同一个 queue 边界。常见误用：

- 用入口 QPS 配下游 connection pool 的等待时间；
- 混合成功、timeout 和被取消请求；
- 在快速增长的 backlog 上假设稳态；
- percentile 代替平均量；
- queue metric 只是瞬时采样，却与长窗平均相乘。

## 利用率与排队的非线性 {#utilization}

若有 $m$ 个等价 server，平均 service time 为 $\operatorname{E}[S]$，简单负载强度为：

$$
\rho =
\frac{\lambda \operatorname{E}[S]}{m}
$$

$\rho < 1$ 只是理想稳态必要条件，不是低延迟保证。service time 与 arrival 有方差、server 不等价、锁与 cache 共享、任务不可抢占时，尾部会更早恶化。

对 GI/G/1 queue，Kingman 近似给出平均等待：

$$
\operatorname{E}[W_q] \approx
\frac{\rho}{1-\rho}
\cdot\frac{c_a^2+c_s^2}{2}
\cdot\operatorname{E}[S]
$$

其中 $c_a$、$c_s$ 是 inter-arrival 与 service time 的变异系数。它揭示三个方向：

1. 利用率靠近 1 时，$\rho/(1-\rho)$ 非线性放大；
2. bursty arrival 增加等待；
3. 高方差 service time，即使均值相同也更糟。

它不直接描述多 server、优先级、finite queue、heavy-tail、retry feedback 或 closed-loop load generator。模型不合适时应换模型或用仿真/实测，不是继续套公式。

## Service time 与 response time {#service-response}

$$
R = W_q + S
$$

慢请求先分成：

- **服务变慢**：CPU instruction 增多、cache miss、GC、I/O device latency、下游 service；
- **等待变长**：run queue、lock、connection pool、worker pool、rate limiter、broker；
- **协议放大**：retry、hedge、fan-out、batch、head-of-line blocking；
- **测量变化**：clock、边界、sampling、route mix、coordinated omission。

只优化函数 CPU，无法修复 connection pool queue；只扩 worker，也可能让数据库同时收到更多并发而崩溃。

## 重试是闭环负载 {#retries}

若每次 attempt 失败后以概率 $r$ 再试，且粗略看作独立几何过程，外部到达率 $\lambda_0$ 产生的 attempt rate 期望为：

$$
\lambda_{\text{attempt}} =
\frac{\lambda_0}{1-r}
$$

$r=0.5$ 时负载翻倍；现实中 dependency 越慢，timeout/失败越多，$r$ 又继续升高，形成正反馈。

安全 retry 需要共同设计：

- operation 是否幂等；
- retry budget；
- exponential backoff 与 jitter；
- per-attempt timeout 和总 deadline；
- 服务端 admission/load shedding；
- circuit breaker 的状态与恢复探测；
- 返回值能否区分 overload 与永久错误。

不同层独立重试会相乘。三层各最多 3 attempt，最坏一次 operation 可触发 $3^3=27$ 个底层 attempt。通常让一个明确层拥有 retry policy，并把 attempt number 和最终 operation 结果分别观测。

## Buffer、背压与准入 {#backpressure}

buffer 吸收 burst，但不能创造长期容量。若 $\lambda > \mu$，backlog 增长率近似：

$$
\frac{dQ}{dt} = \lambda - \mu
$$

无界 queue 将 overload 从“快速拒绝”变成内存增长、超时和过期 work。有限 queue 的容量应来自可接受 queueing delay：

$$
Q_{\max} \approx X \times W_{q,\max}
$$

例如 sustainable throughput 1,000/s，只允许 50 ms 排队，平均 queue budget 约 50 个 work；还要给 burst、方差和调度留余量，并用负载实验校正。

### 背压形式

| 机制 | 作用 | 风险 |
| --- | --- | --- |
| bounded queue | 限制内存与陈旧 work | 满时必须定义 drop/reject |
| semaphore/concurrency limit | 限制 in-flight | limit 固定时可能不适应依赖变化 |
| token bucket | 控制平均率并允许 burst | 不直接限制单请求成本 |
| admission control | 在入口保护稀缺资源 | 优先级与公平性难 |
| load shedding | 过载时快速拒绝 | 调用方重试可再次放大 |
| backpressure protocol | 让 producer 减速 | 跨组织/UDP 等边界未必可传播 |

理想策略优先丢弃已无法在 deadline 内完成、低优先级或可重建的 work，并返回调用方可理解的 overload 信号。随机超时会浪费更多已投入资源。

## 批处理与并发 {#batching}

batch 可摊销固定成本：

$$
S_{\text{item}}(b) =
\frac{S_{\text{fixed}} + S_{\text{variable}}(b)}{b}
$$

但要等待凑 batch，增加 queueing delay；batch 太大还会：

- 占用更多 memory；
- 形成 head-of-line blocking；
- 降低调度公平性；
- 放大单次失败与 retry；
- 让 p99 受最慢 item 支配。

并发也不是越高越好。增加并发直到 bottleneck 饱和后，吞吐不再增长，queue/上下文切换/cache contention/GC 继续增长。最佳 operating point 通常在 knee 之前，而不是峰值刚好崩溃的位置。

## 容量实验：画出整条曲线 {#load-test}

一次只跑“目标 QPS”看不到系统形状。逐步提高 offered load，并同时记录：

- admitted/completed/goodput；
- p50/p90/p99/max 和 timeout/reject；
- queue depth/wait 与 in-flight；
- CPU/steal/run queue、memory/GC/PSI；
- disk/network/device queue；
- dependency 与 connection pool；
- retry/hedge/fan-out；
- telemetry loss。

典型阶段：

1. **linear**：吞吐随负载增长，latency 稳定；
2. **knee**：一个资源接近饱和，tail 开始非线性上升；
3. **saturation**：吞吐趋平，queue 增长；
4. **collapse**：timeout/retry/GC/lock 反馈使 goodput 下降；
5. **recovery**：撤载后是否快速恢复，还是 backlog 继续拖累。

每个阶梯要足够长以经历 warm-up、GC、cache、autoscaling 与下游窗口。随机化或重复顺序，避免温度、频率、背景任务和累积状态冒充负载效应。负载生成器自身也要验证 CPU、socket 与网络未饱和。

### Coordinated omission

closed-loop generator 等上一个 response 后才发下一个；系统 pause 时，它也停止产生本应到达的请求，测得 latency 会偏低。校验工具是否按预定 arrival schedule 记录延误，或至少同时报告 offered schedule、actual send 和 completion。

## 一个容量起点，不是最终答案 {#calculator}

若每个实例有 $m$ 个可独立服务的 slot、平均 service time 为 $s$、目标利用率 $\rho_t$，实例下界可粗估：

$$
n =
\left\lceil
\frac{\lambda_{\text{peak}}s}
{m\rho_t}
\right\rceil
$$

下面的脚本把公式变成可审查的输入：

```python
from math import ceil
def instances(qps: float, service_ms: float, slots: int,
              target_util: float, failure_reserve: int = 1) -> int:
    if qps < 0 or service_ms <= 0 or slots <= 0:
        raise ValueError("workload and capacity must be positive")
    if not 0 < target_util < 1:
        raise ValueError("target_util must be between 0 and 1")
    offered_concurrency = qps * service_ms / 1000
    steady = ceil(offered_concurrency / (slots * target_util))
    return steady + failure_reserve
if __name__ == "__main__":
    print(instances(2400, 35, 16, 0.65))
```

这只适合初始估算。它假设 slot 等价、service time 代表真实资源占用、workload mix 稳定，未包含：

- tail 和 burst；
- shared bottleneck；
- per-instance fixed overhead；
- autoscaling delay；
- AZ/host failure correlation；
- cache cold start；
- retry 与 background work；
- CPU quota、NUMA、memory bandwidth。

最终容量必须用目标 topology 和 failure scenario 实测，并在生产遥测中持续校准。

## Headroom 与故障域 {#headroom}

headroom 不是一个全局固定百分比。至少分别考虑：

- 正常峰值与预测误差；
- 单 instance/host/AZ 失效；
- rolling deployment 的暂时减容；
- autoscaler detection、provision、warm-up 延迟；
- dependency capacity 与 quota；
- emergency telemetry/debug 开销；
- traffic rebalance 和 cache refill。

如果 N+1 只在平均流量成立、峰值时剩余实例全部进入 collapse，它不是真正的故障余量。验证应主动摘除故障域，并观察 goodput、queue 与恢复，而不只看实例数。

## 排障：从时间线与边界开始 {#troubleshooting}

先写四句话：

1. 用户观察到什么结果，何时开始；
2. 影响哪些 operation/region/version/tenant；
3. 哪个变更或外部事件与时间重合；
4. 哪些事实能复现，哪些只是相关。

随后画请求路径：

```text
client
  -> edge/admission
  -> process queue
  -> runtime scheduler
  -> CPU | memory | filesystem | network
  -> dependency
  -> response/retry
```

在每个边界问同一组问题：

- input/output rate 是否守恒；
- in-flight 与 queue 是否增长；
- service time 还是 wait time 增长；
- error/reject/timeout 在哪里首次出现；
- resource utilization 与 saturation 是否一致；
- workload mix 或 payload 是否改变；
- measurement 是否丢失、重命名或换了边界。

### 资源证据矩阵

| 怀疑 | 首要证据 | 深挖 |
| --- | --- | --- |
| CPU | cgroup CPU、run queue、throttle、PSI | PMU、on-CPU profile、frequency/NUMA |
| memory | RSS/working set、fault、reclaim、OOM | allocation profile、heap、page cache |
| GC/runtime | pause、assist、allocation、scheduler | runtime trace/profile、heap age |
| lock | blocked time、futex、contention | off-CPU stack、lock profile、owner |
| disk | latency、IOPS、bytes、queue | block trace、filesystem/page cache |
| network | RTT、loss/retransmit、socket queue | TCP state、packet/flow trace |
| pool | active/waiter/wait duration | owner stack、dependency latency |
| dependency | client/server duration、status | distributed trace、retry/timeout |
| quota | cgroup throttle、rate limit、API quota | controller/config/event timeline |

utilization 表示资源忙的比例，saturation 表示尚未服务的 work。CPU 100% 通常二者相关；memory“利用率高”可能只是有益 page cache，真正压力要看 reclaim、fault、PSI 和 OOM。网络 bandwidth 未满也可能受 RTT、loss、socket buffer 或单 flow window 限制。

### 时间顺序比相关系数更有力

要区分：

- queue 先涨，latency 后涨；
- dependency latency 先涨，本地 in-flight 后涨；
- retry 先涨，CPU 后涨；
- deployment 后 allocation rate 变，GC pause 再变；
- telemetry 规则改变导致“指标突变”，用户结果未变。

trace、log、metric、profile 与 deployment event 应使用统一时间基准，但仍要评估 clock skew。跨 host 绝对 timestamp 有误差时，利用 span 内 duration、消息 sequence 与单调时钟建立局部顺序。

## 压力指标与控制器 {#pressure}

Linux Pressure Stall Information 分别报告 task 因 CPU、memory、I/O 资源不足而 stall 的时间。`some` 表示至少部分 task stalled，`full` 表示所有 non-idle task 同时 stalled；语义与可用项依资源、kernel 和 cgroup 层级而定。

PSI 比“资源用了多少”更接近“work 因资源缺失停了多久”，但仍不是应用 SLO：

- CPU pressure 可能来自同 cgroup 的 background job；
- I/O pressure 不说明是哪个 device/file；
- memory pressure 不等于 leak；
- cgroup 与 host 视角不同；
- rolling average 会平滑瞬时 spike。

将 PSI 与 queue、profile、cgroup limit 和用户 latency 对齐，再决定扩容、隔离还是修代码。

autoscaler 与 circuit breaker 也是 feedback controller。错误设计会振荡：

- scale-out 指标滞后，实例尚未 warm 又继续扩；
- scale-in 太快丢 cache 并触发下一轮扩容；
- breaker 同时 half-open，产生 thundering herd；
- client deadline 短于 queue time，引发无效 work；
- admission 仅按 request 数，不看 cost。

控制器要显式定义采样窗、阈值、hysteresis、cooldown、最大变化率和 failure mode，并在非平稳负载下测试。

## 一次排障的闭环 {#workflow}

1. 固定影响边界、时间窗和版本；
2. 从用户 SLI 验证问题，不从单个资源图开始；
3. 对齐 offered/admitted/completed/goodput；
4. 找到最早增长的 queue、wait、error 或 retry；
5. 判断 service time 与 queueing time；
6. 选择 counter、trace、on/off-CPU profile 或 eBPF；
7. 用一个机制假设预测还应出现什么证据；
8. 做最小、可回滚的实验；
9. 在相同 workload 下复验 SLO 与资源；
10. 修正 capacity model、告警与 runbook。

“重启好了”只能证明状态被清空；还需解释是 leak、backlog、deadlock、cache、connection、controller 还是外部故障，并设计能在下次重启前捕获的证据。

## 常见失败 {#failure-modes}

- 把平均 CPU 当作容量；
- offered load 与 completed throughput 混为一谈；
- 用 p99 套 Little 定律；
- queue 在增长仍假设稳态；
- 扩大 queue 掩盖长期容量不足；
- 加 worker 把 bottleneck 推向共享数据库；
- 每层各自 retry；
- load generator coordinated omission；
- 只测 steady state，不测恢复与故障域；
- autoscaler 指标和 scaling 目标不在同一边界；
- memory 使用高就认定 leak；
- 相关时间线没有机制预测；
- 修改后只看局部 counter，不复验用户 goodput。

## 继续阅读

- 实验设计、置信区间与环境控制：见[基准设计](benchmarking.md)。
- CPU、off-CPU、PMU 和 kernel event：见[采样、perf 与 eBPF](profiling.md)。
- 统一 metric、trace、log 与 profile：见[指标、日志、追踪与连续剖析](observability.md)。
- 程序层并发原语与 memory model：见[语言与运行时](../languages/index.md)。

## Reference

- [Little：A Proof for the Queuing Formula $L=\lambda W$](https://doi.org/10.1287/opre.9.3.383)
- [Kingman：The Single Server Queue in Heavy Traffic](https://doi.org/10.1017/S0305004100036094)
- [Amdahl：Validity of the Single Processor Approach](https://doi.org/10.1145/1465482.1465560)
- [Linux kernel：PSI](https://docs.kernel.org/accounting/psi.html)
- [Linux kernel：Control Group v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)
- [Linux kernel：CPU frequency and scaling](https://docs.kernel.org/admin-guide/pm/cpufreq.html)
- [Google SRE Book：Handling Overload](https://sre.google/sre-book/handling-overload/)
- [Google SRE Book：Addressing Cascading Failures](https://sre.google/sre-book/addressing-cascading-failures/)
- [HdrHistogram：Coordinated Omission](https://hdrhistogram.github.io/HdrHistogram/plotFiles.html)
