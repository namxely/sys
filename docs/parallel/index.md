# 并行计算

并行计算把一个问题分解为可同时推进的工作，并支付调度、同步、通信和数据移动成本。更多执行单元只增加潜在容量；任务依赖、串行部分、内存带宽、拓扑和负载不均决定其中多少能变成真实加速。

## 学习路径

1. [Work、Span 与扩展定律](performance-models.md)：先建立可证明的并行度和可测量的性能上界。
2. [共享内存与 OpenMP](shared-memory-openmp.md)：理解 fork-join、task、数据作用域和同步。
3. [SIMD 与 SIMT](simd-simt.md)：比较向量指令与线程束执行。
4. [CUDA 编程模型](cuda.md)：把 kernel、内存层次、stream 和 occupancy 连成一条执行路径。
5. [MPI 与集合通信](mpi-collectives.md)：从点对点语义走到 collective 算法。
6. [拓扑与通信优化](topology-communication.md)：把 NUMA、PCIe、NVLink 和网络结构纳入放置。

## 并行程序的四个问题

| 问题 | 对应量 | 常见失败 |
| --- | --- | --- |
| 能分多少 | work/span、依赖 DAG | 串行关键路径 |
| 能喂多快 | arithmetic intensity、带宽 | memory bound |
| 要搬多少 | bytes、messages、同步次数 | 通信淹没计算 |
| 是否均衡 | 每 worker 工作与等待 | straggler、热点 |

任何加速比都必须注明 baseline。若串行版本和并行版本使用不同算法、精度或数据布局，速度变化不全来自并行。

## 最小实验纪律

- 固定问题规模与精度，另做 weak scaling。
- 预热、重复，报告中位数和尾部而非只取最快一次。
- 记录核数、线程亲和、NUMA、频率、编译器与 flags。
- 分离 kernel 时间、数据搬运、同步和端到端时间。
- 用 profiler 验证假设，不以“CPU/GPU 利用率高”代替瓶颈分析。

## Reference

- [OpenMP Specifications](https://www.openmp.org/specifications/)
- [MPI 5.0 Standard](https://www.mpi-forum.org/docs/)
- [CUDA Programming Guide](https://docs.nvidia.com/cuda/cuda-programming-guide/)
- [Berkeley: The Landscape of Parallel Computing Research](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2006/EECS-2006-183.html)
