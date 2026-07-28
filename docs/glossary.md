# 术语表

| 术语 | 精确定义 | 相关页面 |
| --- | --- | --- |
| ABI | 二进制接口契约，包括调用约定、对象布局、符号与进程映像约定 | [链接、加载与 ABI](tooling/linking-loading.md) |
| Backpressure | 下游容量不足时把速率约束传播给上游，而不是无限积压 | [Socket 与 I/O](network/sockets-io.md)、[Node.js](languages/nodejs.md) |
| Cache coherence | 多个缓存副本对单一内存位置的写入可见性与序列化规则 | [缓存与一致性](architecture/cache-coherence.md) |
| Consistency | 多个操作或副本对外呈现的可见性与顺序约束 | [复制与共识](distributed/replication-consensus.md) |
| Coroutine | 能在保留执行状态的情况下挂起并稍后恢复的计算 | [协程](concurrency/coroutines.md) |
| DMA | 设备在 CPU 不逐字节搬运的情况下访问内存的机制 | [I/O、中断与 DMA](os/io-interrupt-dma.md) |
| Happens-before | 用于判断操作可见性和数据竞态的跨线程偏序关系 | [原子与内存模型](architecture/atomics-memory-model.md) |
| ISA | 软件可见的处理器指令、寄存器、异常与内存语义 | [ISA 与微架构](architecture/isa-microarchitecture.md) |
| Latency | 单个操作从定义的起点到终点所经历的时间 | [抽象与性能](foundations/abstractions-performance.md) |
| Linearizability | 并发操作可被解释为在调用与返回之间某一点原子发生 | [并发基础](concurrency/foundations.md) |
| NUMA | 内存访问成本依处理器与内存位置而不同的拓扑 | [CPU](architecture/cpu.md) |
| p99 | 99% 样本不超过的分位值，不等于“最慢 1% 的平均值” | [基准设计](performance/benchmarking.md) |
| RAII | 让资源生命周期绑定对象生命周期的 C++ 惯用契约 | [C++](languages/cpp.md) |
| RCU | 读侧低开销、通过宽限期回收旧版本的同步方法族 | [无锁与 RCU](concurrency/lock-free-rcu.md) |
| Throughput | 单位时间完成的工作量 | [性能模型](parallel/performance-models.md) |
| TLB | 缓存虚拟地址到物理地址转换的处理器结构 | [虚拟内存与 TLB](architecture/virtual-memory-tlb.md) |
| Work / Span | 并行计算的总工作量与关键路径长度 | [并行性能模型](parallel/performance-models.md) |
| Write amplification | 逻辑写入引起的更大物理写入量 | [SSD 与 NVMe](storage/ssd-nvme.md) |
