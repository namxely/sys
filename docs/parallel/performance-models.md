# Work、Span 与扩展定律

<a id="work-span"></a>
## Work 与 Span

把并行程序表示为依赖 DAG。每个节点是操作，边是先后约束：

- work $T_1$：所有节点成本之和，也是一处理器时间；
- span $T_\infty$：DAG 最长依赖路径，也称 critical path；
- 平均并行度：$\mathcal P=T_1/T_\infty$。

在 $P$ 个处理器上：

$$
T_P\ge \max\left(\frac{T_1}{P},T_\infty\right)
$$

理想 greedy scheduler 的直觉上界为：

$$
T_P\le \frac{T_1}{P}+O(T_\infty)
$$

因此高 work efficiency 不等于高并行度；一个总工作很小但依赖链很长的算法仍无法扩展。

<a id="speedup"></a>
## Speedup、Efficiency 与 Cost

$$
S_P=\frac{T_1}{T_P},\qquad
E_P=\frac{S_P}{P},\qquad
C_P=PT_P
$$

线性加速 $S_P=P$ 是参照，不是普遍承诺。超线性加速可能来自并行后工作集进入 aggregate cache、不同算法路径或 baseline 不公平，应解释而非直接视作错误。

<a id="amdahl"></a>
## Amdahl：固定问题规模

若串行比例为 $s$，其余可在 $P$ 个处理器理想均分：

$$
S_P=\frac{1}{s+\frac{1-s}{P}},
\qquad
\lim_{P\to\infty}S_P=\frac1s
$$

真实模型还应加入开销 $o(P)$：

$$
T_P=sT_1+\frac{(1-s)T_1}{P}+o(P)
$$

同步、通信和调度常使 $o(P)$ 随规模增加，所以拟合出的“串行比例”不一定是源码中某段固定代码。

<a id="gustafson"></a>
## Gustafson：固定并行运行时间

资源增加时，人们常扩大问题而不是缩短同一任务。令并行机运行时间归一为 1，其中串行部分为 $s$，用单处理器执行放大的并行部分需 $P(1-s)$：

$$
S_P^{\text{scaled}}=s+P(1-s)=P-s(P-1)
$$

Amdahl 和 Gustafson 不是互相否定：前者回答 strong scaling，后者回答 weak/scaled scaling。实验必须说明固定的是输入、每处理器工作还是总时间。

<a id="roofline"></a>
## Roofline

算术强度 $I$ 是每搬运一字节执行的操作数。若峰值计算性能 $\pi$、可持续内存带宽 $\beta$：

$$
\mathrm{performance}\le \min(\pi,\beta I)
$$

ridge point $I^*=\pi/\beta$。$I<I^*$ 时优先减少流量、提高复用；$I>I^*$ 时再看指令吞吐、依赖和 occupancy。使用实测可持续带宽而非厂商理论峰值，且按层次分别计算 L1/L2/DRAM traffic。

<a id="load-balance"></a>
## 负载均衡与调度下界

任务成本为 $w_i$，总 work $W=\sum_iw_i$，最大任务 $w_{\max}$：

$$
T_P\ge \max(W/P,w_{\max})
$$

静态划分开销低，适合规则迭代；动态队列或 work stealing 适合不规则任务，但增加原子操作、局部性损失与调度成本。chunk 太小会调度淹没计算，太大又造成尾部不均。

## 测量清单

1. 先 profile 得到串行热点、同步等待、带宽与任务分布。
2. 分别绘制 strong/weak scaling，至少给 $T_P,S_P,E_P$。
3. 测 work inflation：并行版本执行的指令、bytes、cache misses 是否增加。
4. 记录频率变化和 turbo；单核 baseline 可能运行在更高频率。
5. 对随机或不规则 workload 报告每 worker work 与尾部空闲。

## 从模型走向实现

- [共享内存与 OpenMP](shared-memory-openmp.md) 展示 work/span 如何落到 task、barrier 与调度粒度。
- [SIMD 与 SIMT](simd-simt.md) 把峰值计算与数据布局细化到 lane 和 memory transaction。
- [CUDA 编程模型](cuda.md)用 kernel、tile、stream 和 occupancy 验证 Roofline 判断。
- [MPI 与集合通信](mpi-collectives.md)把 $\alpha$-$\beta$ 通信成本加入跨节点扩展曲线。

## Reference

- [Amdahl: Validity of the Single Processor Approach](https://doi.org/10.1145/1465482.1465560)
- [Gustafson: Reevaluating Amdahl's Law](https://doi.org/10.1145/42411.42415)
- [Blumofe and Leiserson: Scheduling Multithreaded Computations by Work Stealing](https://doi.org/10.1145/324133.324234)
- [Roofline: An Insightful Visual Performance Model](https://escholarship.org/uc/item/3qf383m0)
- [Nsight Compute Roofline documentation](https://docs.nvidia.com/nsight-compute/ProfilingGuide/index.html#roofline-charts)
