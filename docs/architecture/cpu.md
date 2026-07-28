# CPU

现代 CPU 是层次化并行机器：一个插槽包含多个核心，每个核心可能有多个硬件线程和向量执行通道，多个核心通过缓存层次与片上互连共享内存控制器。它优化的是低延迟通用执行，而不是单一“每秒指令数”。

## 核心内部

典型高性能核心包含：

- 取指、分支预测、i-cache 与 ITLB；
- 解码、µop cache、寄存器重命名；
- 乱序调度窗口、重排序缓冲；
- 整数、浮点、向量、分支与 load/store 执行端口；
- L1D、L1I，常有私有或共享 L2；
- 性能监控单元（PMU）。

这些结构的目标是从一个线程中提取 [ILP](pipeline-ilp-branch.md)，并让多个 cache miss 或执行操作重叠。

## SMT 不是第二个核心

Simultaneous Multithreading 让多个硬件线程共享同一核心的大量资源。当一个线程因 miss 或依赖停顿时，另一个线程可使用空闲槽位。收益取决于两者资源互补性；若都争用前端、执行端口、缓存或带宽，总吞吐可能只小幅增加，单线程延迟还可能变差。

调度与容量规划应区分：

- 逻辑 CPU；
- 物理核心；
- cache/NUMA 域；
- 插槽；
- 异构核心类型。

Linux 可从 `/sys/devices/system/cpu/cpu*/topology/` 和 hwloc 获取拓扑，但容器看到的 CPU 集合可能受 cpuset 限制。

## 向量执行

SIMD 指令让一条指令操作多个 lane。实际收益受：

- 数据布局与对齐；
- 循环依赖与别名；
- 尾部处理与掩码；
- gather/scatter 成本；
- 向量频率与功耗；
- 内存带宽。

编译器自动向量化通常比直接绑定某一 intrinsic 更可移植。先查看 `-Rpass=loop-vectorize` 或 GCC `-fopt-info-vec`，再在必要时使用目标 ISA intrinsic，并提供能力检测和标量回退。

## cache、内存与 NUMA

核心私有 cache 优化热点延迟，共享最后级 cache 减少 DRAM 流量并承载一致性目录或过滤器。多插槽系统中，远端内存需经过互连；带宽和延迟都取决于页放置与线程位置。

“first touch”是常见 Linux 策略结果：匿名页往往在首次 fault 的 CPU 所属节点分配。初始化线程和工作线程分离，可能把整个数据集放错节点。并行初始化、显式 NUMA policy 或页迁移需要结合真实负载选择。

## 频率、功耗与温度

CPU 频率随活动核心数、指令类型、温度和功耗预算变化。宽向量、持续满载或同封装加速器都可能改变频率。因而：

- `cycles` 不等于固定时间；
- 标称最高频率不等于持续全核频率；
- 更高 IPC 可能在更低频率下运行；
- 长基准应记录稳态温度和能耗。

能效可以报告每项工作焦耳数：

$$
E_\mathrm{op}=\frac{\int P(t)\,dt}{N_\mathrm{completed}}
$$

功耗接口的采样范围可能是 package、core 或 DRAM，必须写清测量域。

## CPU 受限还是内存受限

用运算强度 $I$ 和可持续内存带宽 $B$ 建立上界：

$$
P_\mathrm{attainable}\le \min(P_\mathrm{peak}, I B)
$$

若循环每元素只做一次加法却搬运多个 cache line，扩展核心数后很快触及带宽；继续优化指令吞吐收益有限。若数据完全驻留 L1 且依赖链很长，DRAM 带宽则无关。

下面的 C++20 triad 是带宽探针，不是完整内存基准：

```cpp
#include <chrono>
#include <cstddef>
#include <iostream>
#include <string>
#include <vector>
int main(int argc, char** argv) {
    std::size_t n = argc > 1 ? std::stoull(argv[1]) : 1ULL << 26;
    std::vector<double> a(n), b(n, 1.0), c(n, 2.0);
    auto t0 = std::chrono::steady_clock::now();
    for (std::size_t i = 0; i < n; ++i) a[i] = b[i] + 3.0 * c[i];
    auto s = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    std::cout << a[n / 2] << ' ' << 3.0 * n * sizeof(double) / s / 1e9 << " GB/s\n";
}
```

`3n` 只计两次读和一次写的有效字节；write allocate、回写、预取和非临时 store 会改变真实流量。应使用足够大的数组、并行版本、NUMA 放置和内存控制器计数器交叉验证。

## PMU：从症状到机制

硬件计数器可观察 cycles、instructions、cache/TLB、branch、stall 等事件。使用纪律：

1. 先确定事件属于哪个 PMU 和计数域；
2. 检查 multiplex 比例与内核/用户态过滤；
3. 事件含义按具体处理器手册解释；
4. 比率必须同时检查分子、分母；
5. 与 wall time、trace 和源级 profile 对齐。

不同微架构的同名事件可能不完全可比。云主机或虚拟机还可能屏蔽 PMU。

## 失败模式

- 用逻辑 CPU 数量当独立核心数；
- 绑线程却不绑定内存；
- 把峰值 FLOPS/带宽当应用可达值；
- 混合不同频率状态比较 IPC；
- 只看一个计数器归因；
- 把 benchmark 的 CPU 分数外推到网络或存储服务；
- 忽略异构核心、SMT 邻居和容器 cpuset；
- 为某一处理器手调指令，却没有运行时分派。

## 跨层连接

- 核心内部见 [流水线、ILP 与分支预测](pipeline-ilp-branch.md)；
- 数据移动见 [缓存一致性](cache-coherence.md) 与 [TLB](virtual-memory-tlb.md)；
- 线程落在哪个核心由 [调度器](../os/scheduling.md) 决定；
- 与吞吐型 [GPU](gpu-simt.md) 对比时，应比较同一工作和精度，而不是宣传峰值。

## Reference

- [Intel 64 and IA-32 Architectures Optimization Reference Manual](https://www.intel.com/content/www/us/en/developer/articles/technical/intel64-and-ia32-architectures-optimization.html)
- [Arm Neoverse Software Optimization Guide](https://developer.arm.com/documentation/109898/latest/)
- [AMD Processor Programming Reference](https://www.amd.com/en/search/documentation/hub.html)
- [Linux CPU Topology](https://www.kernel.org/doc/html/latest/admin-guide/cputopology.html)
- [Linux perf Events and Tool Security](https://www.kernel.org/doc/html/latest/admin-guide/perf-security.html)
- [Williams, Waterman, and Patterson, Roofline: An Insightful Visual Performance Model](https://doi.org/10.1145/1498765.1498785)
- [McCalpin, Memory Bandwidth and Machine Balance in Current High Performance Computers](https://www.cs.virginia.edu/~mccalpin/papers/balance/)
