# 更新日志

## 2026-07-28

首个公开版本建立了从程序语义向下追踪到机器执行、再向外延伸至网络和分布式系统的主干。

- [知识架构](guide/architecture.md)、[学习路线](guide/roadmap.md)与[阅读系统的方法](guide/method.md)给出统一的分层坐标：契约、状态、控制流、数据流、成本、失败与观测。
- 硬件主线连接[数据与内存层次](foundations/data-memory-hierarchy.md)、[ISA 与微架构](architecture/isa-microarchitecture.md)、[缓存一致性](architecture/cache-coherence.md)、[CPU](architecture/cpu.md)和[GPU](architecture/gpu-simt.md)。
- 系统软件主线覆盖[操作系统](os/index.md)、[并发](concurrency/index.md)、[网络](network/index.md)、[存储](storage/index.md)、[并行计算](parallel/index.md)与[分布式系统](distributed/index.md)，并把顺序、队列、复制、持久化和故障边界放进同一套推理框架。
- 程序实现主线从 [C](languages/c.md)、[C++](languages/cpp.md)、[Java 与 JVM](languages/java-jvm.md)、[Go](languages/go.md)、[Rust](languages/rust.md)、[Python](languages/python.md)、[JavaScript](languages/javascript.md)、[TypeScript](languages/typescript.md)、[Node.js](languages/nodejs.md)和 [WebAssembly](languages/webassembly.md) 进入[编译流水线](tooling/compiler-pipeline.md)、[链接与加载](tooling/linking-loading.md)、[调试](tooling/debugging.md)以及[性能与可观测性](performance/index.md)。
- 正文引入可运行或可编译的紧凑实现、LaTeX 推导、语义图表、页内交叉链接和页级 `Reference`，并对导航、代码、公式、图表、内部链接及桌面与移动端渲染进行持续校验。
