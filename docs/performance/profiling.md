# 采样、perf 与 eBPF：从热点到机制

profile 回答“执行资源主要花在哪里”，trace 回答“事件以什么顺序发生”，hardware counter 回答“处理器观察到多少类微架构事件”。它们互补而非互换：只有 CPU stack sample，无法解释等待队列；只有 request trace，也无法解释同一 span 内为何 cache miss。

本文以 Linux man-pages 6.18 的 `perf_event_open(2)` UAPI、Linux kernel 文档和 OpenTelemetry/eBPF 官方资料为基准。PMU event、eBPF helper、BTF、attach type 与权限都依赖实际 kernel、CPU 和工具版本，运行前记录 `uname -r`、`perf version`、`bpftool feature probe`。

## 四类观测 {#measurement-types}

| 方法 | 数据 | 优点 | 主要偏差/成本 |
| --- | --- | --- | --- |
| counting | cycles、instructions、faults 总数 | 开销低、适合对比 | 没有位置与时间结构 |
| sampling | 周期性采 PC/call stack | 开销可控、定位热点 | 统计误差、skid、unwind |
| instrumentation | 函数/事件显式 start/end | 语义精确 | code path 开销、遗漏未埋点 |
| tracing | 时间序列事件与上下文 | 因果和等待可见 | 数据量、lost events、时钟关联 |

先根据问题选择。CPU utilization 高时 sampling；latency 高但 CPU 低时看 off-CPU/queue/trace；怀疑 cache/branch 时看 PMU；怀疑特定 syscall/lock 路径时用 tracepoint/eBPF。

## `perf_event_open` 模型 {#perf-event}

Linux `perf_event_open` 创建一个 file descriptor，对应 counting 或 sampled event。参数选择：

- 哪个 thread/process 或 CPU；
- event type/config；
- user/kernel/hypervisor 是否计入；
- sample period/frequency；
- sample payload：IP、TID、time、callchain、register、stack；
- group 与 output ring buffer。

group 让一组 event 作为单位调度，便于计算比率；若硬件 counter 不够，kernel 可能 multiplex。读数常包含：

- `value`；
- `time_enabled`；
- `time_running`。

缩放估计：

$$
\hat{C} = C_{\text{raw}}\frac{T_{\text{enabled}}}{T_{\text{running}}}
$$

当 running/enabled 很低或 workload 非平稳时，线性缩放可能误导。减少同时 event 数，分多轮并随机化顺序。

### 常用 `perf stat`

```bash
perf stat -r 5 \
  -e cycles,instructions,branches,branch-misses,cache-misses \
  -- ./app input
```

常见派生量：

$$
\text{IPC} = \frac{\text{instructions}}{\text{cycles}}
$$

$$
\text{branch miss rate} =
\frac{\text{branch-misses}}{\text{branches}}
$$

IPC 低不是根因。可能是 cache miss、branch、dependency chain、front-end starvation、频率、sleep 或不同 instruction mix；还要确认 event 是否来自同一时间窗口、是否 multiplex，以及 CPU hybrid core 的 PMU 类型。

## Sampling profile {#sampling}

```bash
perf record -F 99 -g --call-graph dwarf -- ./app input
perf report
```

若每个 sample 独立且热点真实占 CPU 比例 $p$，$N$ 个样本中计数近似 binomial，标准误差：

$$
\operatorname{SE}(\hat{p}) \approx
\sqrt{\frac{\hat{p}(1-\hat{p})}{N}}
$$

实际 sample 有自相关和调度偏差，公式只给直觉。99 Hz 这类非整周期频率可减少与 workload 周期同步，但采样率应按开销和最小可见 hotspot 设计。

### On-CPU 与 Off-CPU

- on-CPU stack：线程运行时在哪些调用链；
- off-CPU duration：线程为何睡眠、等待多久、由谁唤醒；
- run-queue latency：runnable 后多久得到 CPU；
- wall-clock profile：可同时看到等待和执行，但解释需区分状态。

一个请求慢而 on-CPU profile 正常，常见原因是 lock、I/O、调度或下游。把 off-CPU stack 与 trace span 对齐比继续提高 CPU sample 更有效。

### Call stack 质量

unwind 可依赖：

- frame pointer；
- DWARF Call Frame Information；
- LBR/硬件 call stack；
- runtime 专用 stack walker；
- JIT map/perf jitdump。

`[unknown]` 可能来自缺 symbol、错误 build ID、被 omit 的 frame pointer、不完整 unwind、JIT 未注册、栈损坏或权限。先修栈质量，再解释火焰图。

### Skid

PMU overflow 到 kernel 记录 IP 之间可能已执行额外指令，sample 落在事件之后，这叫 skid。precise event/PEBS/IBS 可降低但受 CPU 支持限制；不要把单条 instruction 的 sample 数视为精确 fault 计数。

## 火焰图：聚合栈的视图 {#flame-graphs}

火焰图把相同 stack prefix 聚合：

- 横向宽度表示样本占比，不表示时间先后；
- 纵向是调用深度；
- 颜色通常不具有性能语义；
- 顶部宽 frame 是 on-CPU 叶/被采样位置；
- 底部宽 frame 是大量调用的祖先，不一定可优化。

差分火焰图比较两个 profile，但只有在 workload、采样、symbol 和归一化一致时才有效。火焰图不能显示 request timeline、因果先后、off-CPU 原因或单次 p99；这些需要 trace/off-CPU profile。

## eBPF：受验证的内核可编程观测 {#ebpf}

eBPF program 加载后先经过 verifier，再可 attach 到 tracepoint、kprobe、uprobe、network hook、perf event 等。基本构件：

- program type 决定 context 与允许 helper；
- verifier 追踪 register/stack 类型、范围与 path，拒绝无法证明安全的程序；
- maps 在 kernel/user/program 间共享状态；
- ring buffer/perf buffer 把 event 送到 user space；
- JIT 可把 eBPF instruction 转成本机 code；
- BTF/CO-RE 帮助适配 kernel type layout。

verifier 接受不代表观测语义正确。它主要证明内核安全相关约束，不证明 map key 不碰撞、事件不丢、单位正确或 attach point 稳定。

### 选择 attach point

| 入口 | 稳定性与语义 |
| --- | --- |
| tracepoint | kernel 暴露的明确 event，通常优先 |
| kprobe/kretprobe | 内核函数实现边界，跨 kernel 易漂移 |
| uprobe/uretprobe | user binary 地址/symbol，受版本、inline、PIE 影响 |
| USDT | 应用显式定义的稳定语义 probe |
| fentry/fexit | BTF 支持下更直接，依赖 kernel/config |

优先语义稳定的 tracepoint/USDT；只有缺失时才绑定内部函数，并把 kernel/build ID 写入采集 metadata。

### 紧凑延迟直方图

以下 bpftrace 脚本按 thread 记录 `read` syscall 进入到退出的时间：

```bpftrace
tracepoint:syscalls:sys_enter_read
{
  @start[tid] = nsecs;
}
tracepoint:syscalls:sys_exit_read
/@start[tid]/
{
  @latency_us = hist((nsecs - @start[tid]) / 1000);
  delete(@start[tid]);
}
```

它测的是 syscall elapsed，不是磁盘 device latency：可能包含 page cache、pipe/socket、阻塞、调度与信号。thread 在脚本 attach 前已进入、进程退出或事件丢失会留下/漏掉状态，生产脚本需考虑 map 上限和 cleanup。

### Verifier 的抽象解释

kernel 文档示例显示 verifier 从入口沿 CFG path 模拟 instruction，追踪：

- register 是否初始化；
- scalar range；
- pointer 类型与允许 arithmetic；
- stack slot 状态；
- helper 参数/返回；
- reference/lock 等资源释放。

循环已在现代 kernel 支持有界形式，但 verifier complexity、precision 和 feature 会随版本变化；“旧文章说 eBPF 禁止循环”不能代表当前 kernel。以目标 `bpftool feature` 和 verifier log 为准。

## 观测开销与安全 {#overhead-safety}

观测会改变系统：

- 过高 sample frequency 触发更多 interrupt/NMI；
- DWARF unwind 复制 user stack；
- 高频 tracepoint 每事件 map/update/output；
- 大 ring buffer 占内存，小 buffer 丢事件；
- string/stack aggregation 增加 CPU；
- uprobes 软件 trap 放大热点函数成本；
- BPF map 全局 key 产生 contention。

先在 canary 测 overhead：

$$
\text{overhead} =
\frac{X_{\text{instrumented}} - X_{\text{baseline}}}
{X_{\text{baseline}}}
$$

分别看 CPU、latency、throughput、RSS 和 lost event。数据量控制顺序通常是：内核内聚合 > 采样 > 过滤 > 限流 > 全量输出。

权限也属于设计。现代 Linux 可用 `CAP_PERFMON` 限定 performance monitoring；`perf_event_paranoid`、BPF unprivileged policy、LSM 和 container namespace 进一步控制。不要为了 profile 给应用长期 `CAP_SYS_ADMIN`。

## 从 profile 到优化 {#workflow}

1. 用 endpoint/SLO 定义症状与时间窗；
2. 验证 workload、CPU/NUMA/cgroup 与版本；
3. 用 coarse counter 判定 CPU、fault、context-switch、I/O；
4. 采 on/off-CPU stack；
5. 用 trace/eBPF 验证等待、queue 与内核路径；
6. 回到源码/IR/assembly 检查机制；
7. 做一个有回滚的改动；
8. 用原始 benchmark 和生产信号复验。

热点优化价值近似受 Amdahl 限制。若热点占 $p$，局部加速 $s$：

$$
S = \frac{1}{(1-p)+p/s}
$$

profile 中 5% 的函数即使无限加速，整体上限也约 $1/0.95$；除非它支配尾延迟、能耗或容量，而不是平均 CPU。

## 常见失败 {#failure-modes}

- 把 counter 名字当成跨 CPU 等价 event；
- multiplex 很重仍直接比较 raw count；
- 用 on-CPU profile 解释 I/O wait；
- symbol/unwind 质量差仍相信栈占比；
- 把火焰图横轴当时间线；
- 用 kprobe 内部函数却不固定 kernel；
- eBPF event lost 未监控；
- map key 无界造成内存或 eviction；
- profile 进程而遗漏 child、cgroup 或 short-lived task；
- 采样环境与出问题的 cgroup/NUMA 不同；
- 观测开销本身制造尾延迟；
- 得到热点后未做端到端 before/after。

## 继续阅读

- profile 前先建立可靠实验：见[基准设计](benchmarking.md)。
- 把 sample 与 request 关联：见[指标、日志、追踪与连续剖析](observability.md)。
- 从 queue/saturation 判断采什么：见[容量与系统化排障](capacity-troubleshooting.md)。

## Reference

- [Linux `perf_event_open(2)`](https://man7.org/linux/man-pages/man2/perf_event_open.2.html)
- [Linux `perf-stat(1)`](https://man7.org/linux/man-pages/man1/perf-stat.1.html)
- [Linux kernel: Perf ring buffer](https://docs.kernel.org/userspace-api/perf_ring_buffer.html)
- [Linux kernel: Perf security](https://docs.kernel.org/admin-guide/perf-security.html)
- [Linux kernel: eBPF verifier](https://docs.kernel.org/bpf/verifier.html)
- [Linux `bpf(2)`](https://man7.org/linux/man-pages/man2/bpf.2.html)
- [Linux BPF helpers](https://man7.org/linux/man-pages/man7/bpf-helpers.7.html)
- [Linux kernel: libbpf overview](https://docs.kernel.org/bpf/libbpf/libbpf_overview.html)
- [bpftrace Reference Guide](https://bpftrace.org/docs/release_024/stdlib)
- [Brendan Gregg: Flame Graphs](https://www.brendangregg.com/flamegraphs.html)
- [Amdahl: Validity of the Single Processor Approach](https://doi.org/10.1145/1465482.1465560)
