# 共享内存与 OpenMP

共享地址空间让线程通过普通 load/store 协作，但“地址相同”不意味着观察顺序自动一致。正确性由语言/OpenMP 内存模型、同步操作与数据作用域决定；性能又受 cache coherence、NUMA 和 false sharing 约束。

<a id="fork-join"></a>
## Fork-Join 与数据环境

OpenMP parallel region 创建 team，结束处默认 barrier。变量可能是 `shared`、`private`、`firstprivate` 或 reduction。应优先 `default(none)` 强迫显式分类：

```cpp
#include <omp.h>
#include <cstddef>
double sum(const double *a, std::size_t n) {
    double s = 0.0;
    #pragma omp parallel for default(none) shared(a, n) reduction(+:s) schedule(static)
    for (std::size_t i = 0; i < n; ++i) s += a[i];
    return s;
}
```

浮点 reduction 改变结合顺序，结果通常不 bitwise identical。需要可复现时定义固定归约树、补偿求和与误差界，不能只加 `critical`。

<a id="memory-model"></a>
## Happens-Before 与同步

data race 是两个线程并发访问同一位置、至少一个写，且没有足够同步。barrier、lock、atomic 和特定 OpenMP construct 建立同步关系；`volatile` 不是线程同步。

| 原语 | 适合 | 风险 |
| --- | --- | --- |
| `atomic` | 单位置 read-modify-write | 争用、内存序 |
| `critical` | 短小复合不变量 | 全局串行化 |
| lock | 跨作用域临界区 | 死锁、优先级反转 |
| barrier | 阶段边界 | straggler 放大 |
| reduction | 可结合聚合 | 数值顺序变化 |

锁保护的不只是代码片段，而是不变量。锁外读取同一共享状态仍可能 race。

<a id="tasks"></a>
## Task 与依赖

不规则递归、流水线可用 task。task creation 有固定成本，应设置粒度阈值；`depend` 描述内存区域依赖，但程序仍必须保证地址范围正确、对象生命周期覆盖任务。

```cpp
void mergesort(int *a, int *tmp, int l, int r) {
    if (r - l < 2048) { serial_sort(a + l, r - l); return; }
    int m = l + (r - l) / 2;
    #pragma omp task shared(a, tmp) firstprivate(l, m)
    mergesort(a, tmp, l, m);
    #pragma omp task shared(a, tmp) firstprivate(m, r)
    mergesort(a, tmp, m, r);
    #pragma omp taskwait
    merge(a, tmp, l, m, r);
}
```

顶层需在 `parallel` + `single` 中调用，否则可能只有一个线程执行或重复创建根任务。

<a id="false-sharing"></a>
## False Sharing 与 NUMA

两个线程写不同变量，但变量位于同一 cache line，coherence 仍会来回转移所有权。这是 false sharing。padding/align、按线程分块并在最后归约通常比每次更新共享计数器好。

NUMA 上 first touch 决定物理页初始位置。主线程串行初始化、远端线程并行使用，会造成远端内存访问。并行初始化、线程绑定和数据分区必须一致。

<a id="scheduling"></a>
## 调度选择

- `static`：预分配，开销低且局部性稳定；
- `dynamic,k`：完成一个 chunk 再取，缓解不均；
- `guided`：chunk 逐渐缩小；
- `collapse(n)`：合并规则嵌套循环迭代空间。

选择依据是每次迭代方差与局部性，而非“dynamic 更并行”。测量应记录 `OMP_NUM_THREADS`、`OMP_PROC_BIND`、`OMP_PLACES` 和 runtime 实现。

## 失败与测量

- race 可能因加日志或调度变化消失；用 ThreadSanitizer 等工具扩大证据。
- barrier 时间高可能是负载不均，也可能是前一阶段 cache miss/NUMA 差异。
- oversubscription 会引入调度，尤其伤害 busy-wait runtime。
- nested parallelism 可能创建过多线程或被 runtime 串行化。

先测每线程工作、锁等待、barrier wait、cache line invalidation 与 NUMA traffic，再决定改变算法、布局还是调度。

## 相邻问题

- [Work、Span 与扩展定律](performance-models.md)帮助判断任务粒度、关键路径与理论加速上限。
- [SIMD 与 SIMT](simd-simt.md) 把线程级并行进一步连接到单核向量执行。
- [拓扑与通信优化](topology-communication.md)解释 affinity、first touch 与 NUMA placement 的系统代价。

## Reference

- [OpenMP API 6.0 Specification](https://www.openmp.org/specifications/)
- [OpenMP API Examples](https://github.com/OpenMP/Examples)
- [OpenMP 5.2 Memory Model](https://www.openmp.org/spec-html/5.2/openmpse4.html)
- [OpenMP 5.2 Tools Interface (OMPT)](https://www.openmp.org/spec-html/5.2/openmpch19.html)
- [Linux NUMA memory policy](https://docs.kernel.org/admin-guide/mm/numa_memory_policy.html)
