# 流水线、ILP 与分支预测

提高主频不能无限缩短一条指令的组合逻辑路径，处理器因此把执行拆成多级流水。流水只能让不同指令重叠；要进一步提高每周期完成工作量，还需并行取指、宽解码、寄存器重命名、动态调度和分支预测。这些机制共同开发指令级并行（ILP）。

## 流水线的理想与现实

理想 $k$ 级流水处理 $n$ 条独立指令，时间从 $nk$ 个级时近似降为 $k+n-1$ 个级时。现实会遇到 hazard：

- **结构冲突**：多条指令争用同一端口或单元；
- **数据依赖**：消费者等待生产者；
- **控制依赖**：下一条指令地址尚未确定；
- **内存依赖**：load/store 地址或先后关系不确定；
- **长延迟事件**：cache miss、TLB miss、除法等。

吞吐与延迟必须分开。例如乘法单元可能每周期接收一条新指令，却需若干周期才产生结果。独立乘法看吞吐，链式乘法看延迟。

## 真依赖与假依赖

若指令 B 读取 A 写入的值，存在 RAW 真依赖，不能被重命名消除。WAR 和 WAW 只因有限架构寄存器复用而出现，可通过物理寄存器重命名解除。

```text
A: r1 = r2 + r3
B: r4 = r1 * r5   # RAW，必须等待
C: r2 = r6 + r7   # 对 A 是 WAR，可重命名
D: r1 = r8 + r9   # 对 A 是 WAW，可重命名
```

乱序执行并不违反程序语义：处理器只在操作数与资源就绪时提前执行，最终仍按顺序提交架构状态。

## 一个抽象的乱序状态机

1. **fetch**：按预测 PC 取指；
2. **decode/rename**：转成内部操作，分配物理寄存器和重排序缓冲项；
3. **dispatch**：进入保留站、load/store queue；
4. **issue**：操作数和执行端口就绪后发射；
5. **writeback**：结果唤醒依赖者；
6. **retire**：队首指令确认无异常后提交；
7. **recover**：错误预测或异常时清除年轻操作并恢复映射。

窗口越大，越有机会在一次长延迟之外找到独立工作，但面积、功耗、旁路网络和恢复成本也上升。

## 分支预测为什么必要

宽前端每周期需要多个正确路径字节。若等分支真正执行后再取下一块，深流水会频繁空转。预测器通常回答两个问题：

- 方向：条件分支取或不取；
- 目标：取分支、间接跳转和返回要去哪里。

BTB 缓存分支目标，返回地址栈预测函数返回；方向预测从简单饱和计数器发展到利用局部/全局历史、路径相关和多表组合的预测器。

两位饱和计数器的状态可以写成：

```text
00 strongly not-taken
01 weakly not-taken
10 weakly taken
11 strongly taken
```

实际结果为 taken 时状态加一，not-taken 时减一，并在边界饱和。它能容忍循环退出时的一次反常，而不会立刻翻转长期预测。

### 错误预测成本

错误预测需要丢弃错误路径的年轻操作并重启前端。近似损失：

$$
\Delta\mathrm{CPI}\approx
f_\mathrm{branch}\cdot r_\mathrm{mispredict}\cdot P_\mathrm{recovery}
$$

其中分支频率、错误率和恢复周期都依赖程序与具体核心。PMU 的 `branch-misses` 是重要证据，但它和源代码分支不是简单一一对应：编译器可用条件移动、向量掩码或跳转表改变控制流。

## memory disambiguation

```text
store [p] = x
y = load [q]
```

只有当 $p\ne q$ 时 load 才可越过较老 store。地址尚未算出时，处理器可保守等待，或预测无别名并在冲突被发现后回放。编译器的别名分析解决静态部分，load/store queue 解决动态部分。

语言层的 `restrict`、类型别名规则和数据布局会影响编译器是否能重排；硬件 speculation 仍必须保证最终结果符合 ISA。

## ILP 的软件形状

下面两个循环做相同数量加法。单累加器形成一条长依赖链，多累加器暴露独立工作：

```cpp
double sum1(const double* a, std::size_t n) {
    double s = 0;
    for (std::size_t i = 0; i < n; ++i) s += a[i];
    return s;
}
double sum4(const double* a, std::size_t n) {
    double s0 = 0, s1 = 0, s2 = 0, s3 = 0;
    std::size_t i = 0;
    for (; i + 4 <= n; i += 4) {
        s0 += a[i]; s1 += a[i + 1]; s2 += a[i + 2]; s3 += a[i + 3];
    }
    for (; i < n; ++i) s0 += a[i];
    return (s0 + s1) + (s2 + s3);
}
```

但浮点归约次序改变，结果可能有低位差异；编译器也可能自动向量化。必须用优化报告与反汇编确认生成代码，再用目标机器测量。

## 分支还是无分支

无分支代码并非总快。考虑统计大于阈值的元素：

```cpp
std::size_t count_gt(const int* a, std::size_t n, int t) {
    std::size_t c = 0;
    for (std::size_t i = 0; i < n; ++i) c += static_cast<unsigned>(a[i] > t);
    return c;
}
```

编译器可能生成 `setcc`、条件移动或向量比较。若分支高度可预测，真正分支可能更省操作；若数据随机且分支接近 50%，掩码方案可避免高错误率。答案取决于目标 ISA、编译器、数据分布和是否向量化。

## 前端、后端与 top-down

性能瓶颈可先粗分：

- retiring：槽位用于最终提交的有用工作；
- bad speculation：错误路径或机器清空；
- frontend bound：取指、i-cache、ITLB、解码供给不足；
- backend bound：执行资源或内存等待。

Intel Top-down Microarchitecture Analysis Method 给出具体事件组合；其他厂商和架构有不同事件。分类应当作为定位入口，而不是跨 CPU 比较的通用分数。

## 怎样测量

### 构造两个对照维度

1. 依赖链 vs 多条独立链，观察延迟与吞吐；
2. 可预测数据 vs 随机数据，观察分支错误；
3. 热代码 vs 大代码体积，观察 i-cache/ITLB；
4. 小工作集 vs 大工作集，区分执行端与内存端。

Linux 示例：

```bash
perf stat -r 9 -e cycles,instructions,branches,branch-misses,cache-misses ./bench
perf record -g -e cycles:u ./bench
perf report
```

先用 `perf list` 确认目标 PMU 事件；虚拟机可能不暴露完整 PMU，NMI watchdog 也可能占用计数器。

### 静态分析的边界

LLVM MCA 可基于处理器调度模型估算基本块的端口压力和吞吐，但不会完整模拟 cache、分支预测、动态地址和 OS 干扰。它适合验证“这个基本块是否有明显依赖/端口瓶颈”，不替代真机测量。

## 失败模式

- 用 IPC 单独判断好坏，忽略总指令数；
- 把一条指令的 latency 当 reciprocal throughput；
- 认为乱序执行可以跨越所有依赖；
- 用随机输入测分支，却生产数据高度偏斜；
- 手写 branchless 代码阻碍编译器向量化；
- 展开循环过度，导致寄存器溢出或指令缓存压力；
- 将某款核心的端口表当 ISA 保证；
- 忽略错误预测带来的微架构状态和安全边界。

## 跨层连接

- 指令编码和 ABI 来自 [ISA](isa-microarchitecture.md)；
- cache、TLB 与内存依赖使后端停顿，参见 [缓存一致性](cache-coherence.md) 和 [虚拟内存](virtual-memory-tlb.md)；
- 调度迁移、SMT 邻居和频率策略来自 [CPU](cpu.md) 与 [操作系统调度](../os/scheduling.md)；
- C++ 重排合法性由 [原子与内存模型](atomics-memory-model.md) 界定。

## Reference

- [Tomasulo, An Efficient Algorithm for Exploiting Multiple Arithmetic Units](https://doi.org/10.1147/rd.111.0025)
- [Yeh and Patt, Two-Level Adaptive Training Branch Prediction](https://doi.org/10.1145/123465.123475)
- [Seznec and Michaud, A Case for (Partially) Tagged Geometric History Length Branch Prediction](https://inria.hal.science/inria-00070410)
- [Intel 64 and IA-32 Architectures Optimization Reference Manual](https://www.intel.com/content/www/us/en/developer/articles/technical/intel64-and-ia32-architectures-optimization.html)
- [Intel VTune Cookbook: Top-down Microarchitecture Analysis Method](https://www.intel.com/content/www/us/en/docs/vtune-profiler/cookbook/2024-1/top-down-microarchitecture-analysis-method.html)
- [LLVM Machine Code Analyzer](https://llvm.org/docs/CommandGuide/llvm-mca.html)
- [Linux perf stat manual](https://www.man7.org/linux/man-pages/man1/perf-stat.1.html)
