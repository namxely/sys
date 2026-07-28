# 系统抽象与性能度量

系统抽象的价值不在于隐藏一切，而在于把变化限制在可替换的边界内：程序依赖 ISA 而不依赖某条流水线，进程依赖虚拟地址而不依赖某个物理页框，文件描述符依赖字节流或对象接口而不依赖设备寄存器。性能分析则反过来穿透这些边界，找到哪一层的资源约束正在主导结果。

## 抽象、机制与策略

三个词经常被混在一起：

- **抽象**：定义上层看到的对象和操作，例如进程、虚拟地址、文件和 future。
- **机制**：提供实现能力，例如页表、定时器中断、DMA、原子指令。
- **策略**：决定机制何时以及如何使用，例如页面淘汰、任务调度、I/O 合并。

同一抽象可以有多种机制，同一机制也可承载不同策略。把它们拆开，才能判断某个结论是接口保证，还是 Linux 6.x、某一 CPU 或某一运行时的选择。

## 四种证据边界

| 类型 | 能回答什么 | 不能自动推出什么 |
| --- | --- | --- |
| 标准或规格 | 合法程序可依赖的行为 | 某款实现的时延和内部结构 |
| 源码与设计文档 | 某版本如何实现 | 另一版本、平台或配置也相同 |
| 性能计数器与 trace | 某次运行发生了什么 | 没有采样偏差、归因一定正确 |
| 端到端实验 | 真实负载的最终结果 | 单一机制就是因果来源 |

好的论证会把四者串起来：规格界定可能空间，源码提出机制假设，计数器验证中间事件，端到端实验验证用户价值。

## 性能不是一个数字

### 延迟、吞吐与带宽

延迟 $L$ 是一项工作从提交到完成的时间；吞吐 $X$ 是单位时间完成的工作数；带宽 $B$ 是单位时间传输的数据量。并发系统中，吞吐增加并不保证尾延迟改善。

在稳定系统中，Little 定律把平均在途数量 $N$、到达或完成速率 $X$ 与平均停留时间 $L$ 联系起来：

$$
N=XL
$$

若服务每秒完成 $50{,}000$ 个请求，平均端到端延迟为 $4\ \mathrm{ms}$，则平均约有 $200$ 个请求在系统中。若观测到的在途数远高于这个值，要检查统计窗口、重试、丢弃和“完成”的定义是否一致。

### 利用率不是效率

资源利用率接近 $100\%$ 只表示资源忙，并不表示工作有效。CPU 可能忙于自旋、重试或缺页；GPU 可能驻留许多 warp，却因内存依赖无法发射；磁盘队列很深，可能只是尾延迟已经失控。

对单服务台的简单排队模型，利用率 $\rho$ 接近 $1$ 时等待时间会非线性上升。真实系统的到达分布、服务时间、多队列与优先级更复杂，但“留出吸收突发的余量”仍是重要直觉。

### 分位数与尾部

平均值会掩盖长尾。报告 p50、p90、p99 之前，必须说明：

- 是对请求、连接、时间窗口还是主机先聚合；
- 超时和失败是否进入分布；
- coordinated omission 是否被避免；
- 采样时钟是否单调，测量代码是否改变被测对象。

若客户端等待上一个请求完成后才发下一个请求，系统停顿期间没有产生本应到达的请求，直方图会低估长尾。这就是 coordinated omission。

## 工作、跨度与扩展上限

并行程序的总工作量记为 $T_1$，无限处理器下的关键路径长度记为 $T_\infty$。在 $P$ 个处理器上：

$$
T_P\ge\max\left(\frac{T_1}{P},T_\infty\right)
$$

因此并行度上限约为 $T_1/T_\infty$。Amdahl 定律从另一角度描述固定工作负载：若可加速比例为 $p$，该部分加速 $s$ 倍，总加速比为

$$
S=\frac{1}{(1-p)+p/s}
$$

它提醒我们：优化占总时间 $1\%$ 的函数，即使让它免费，整体也最多改善约 $1.01$ 倍。实际还要加入通信、同步、负载不均与额外工作。

## 从 CPI 到端到端时间

CPU 时间常写成：

$$
T_\mathrm{CPU}=N_\mathrm{inst}\times \mathrm{CPI}\times T_\mathrm{cycle}
$$

这不是三个独立旋钮。编译器为了减少指令数可能增加长依赖链；提高频率可能降低每周期可完成工作或触发功耗限制；CPI 又是缓存、分支、执行端口和前端共同作用的结果。顶层分解用于组织问题，不应被误读成线性因果。

对于流水化服务，端到端时间可以先分解为：

$$
L=L_\mathrm{queue}+L_\mathrm{service}+L_\mathrm{network}+L_\mathrm{retry}
$$

再把服务时间继续分解为 CPU、内存、I/O 与同步等待。每次只在证据支持时向下钻一层。

## 一套可复现的微基准

下面的 C++20 程序测量一个函数的批量执行时间。批量是为了摊薄计时器和循环控制开销；`DoNotOptimize` 通过编译器屏障阻止结果被删除，但它不等价于硬件内存屏障。

```cpp
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <vector>
template<class T> inline void DoNotOptimize(T const& v) {
#if defined(__GNUC__) || defined(__clang__)
    asm volatile("" : : "g"(v) : "memory");
#else
    volatile auto sink = v;
    (void)sink;
#endif
}
std::uint64_t run(std::size_t n) {
    std::uint64_t x = 1;
    for (std::size_t i = 0; i < n; ++i) x = x * 6364136223846793005ULL + 1;
    DoNotOptimize(x);
    return x;
}
int main() {
    using clock = std::chrono::steady_clock;
    constexpr std::size_t n = 10'000'000;
    std::vector<double> samples;
    for (int warm = 0; warm < 3; ++warm) run(n);
    for (int i = 0; i < 21; ++i) {
        auto t0 = clock::now();
        run(n);
        auto t1 = clock::now();
        samples.push_back(std::chrono::duration<double, std::nano>(t1 - t0).count() / n);
    }
    std::ranges::sort(samples);
    std::cout << "median_ns_per_iter=" << samples[samples.size() / 2] << '\n';
}
```

编译时记录完整命令，例如：

```bash
c++ -O3 -DNDEBUG -std=c++20 bench.cpp -o bench
taskset -c 2 perf stat -r 7 -e cycles,instructions,branches,branch-misses,cache-misses ./bench
```

`taskset` 与这些 `perf` 事件是 Linux 接口；事件可用性和含义取决于处理器、内核与权限。macOS 应使用 Instruments 或 `xctrace`，不能把命令直接照搬。

## 实验设计

### 固定不变量

记录：

- CPU、微码、内存拓扑、NUMA 节点与 SMT 状态；
- 内核、编译器、链接器与库版本；
- 编译参数、输入数据、线程亲和性；
- governor、睿频、温度与功耗限制；
- 热身、迭代次数、随机种子和原始样本。

### 基线与对照

先测空循环或空请求，估计测量框架本身的成本。每次改变一个主要变量，使用交错顺序运行基线和候选，避免温度或后台负载随时间漂移造成伪差异。

### 报告分布

保留原始样本，给出中位数、分位数和离散程度。若样本相关或存在阶段变化，单纯置信区间会误导，应展示时间序列并解释稳态区间。

## 常见失败模式

- **把 wall time 当 CPU time**：阻塞、抢占和 I/O 都进入 wall time。
- **只看 IPC**：更高 IPC 的程序可能执行更多指令，最终更慢。
- **只跑一次**：频率、页缓存、JIT、分配器和后台任务都可能主导单次结果。
- **数据集太小**：全部进入缓存后，测到的不是生产路径。
- **微基准过度外推**：孤立指令吞吐不能代表依赖链、前端和内存共同作用的应用。
- **同时优化多个层次**：结果改善了，却无法知道哪个变化有效。
- **把相关当因果**：cache miss 与慢请求同时增加，可能都由调度迁移或数据规模变化造成。

## 诊断顺序

1. 明确用户可感知指标和 SLO。
2. 验证负载生成器没有先饱和。
3. 画吞吐—并发—尾延迟曲线，定位膝点。
4. 用 CPU、内存、磁盘、网络利用率和队列判断资源类别。
5. 用 trace 定位等待，用 PMU 定位执行效率。
6. 设计只改变一个机制的对照实验。
7. 回到端到端负载验证收益与回归。

## Reference

- [SPEC CPU 2017 Overview](https://www.spec.org/cpu2017/Docs/overview.html)
- [SPEC CPU 2017 Run and Reporting Rules](https://www.spec.org/cpu2017/Docs/runrules.html)
- [Amdahl, Validity of the Single Processor Approach to Achieving Large Scale Computing Capabilities](https://doi.org/10.1145/1465482.1465560)
- [Little, A Proof for the Queuing Formula: L = λW](https://doi.org/10.1287/opre.9.3.383)
- [Intel 64 and IA-32 Architectures Optimization Reference Manual](https://www.intel.com/content/www/us/en/developer/articles/technical/intel64-and-ia32-architectures-optimization.html)
- [Linux perf stat manual](https://www.man7.org/linux/man-pages/man1/perf-stat.1.html)
- [C++ working draft: time utilities](https://eel.is/c++draft/time)
