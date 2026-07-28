# 计算机体系结构

体系结构连接软件语义与硬件实现。ISA 规定软件能够依赖的指令、寄存器、异常和内存行为；微架构决定这些指令如何被预测、拆分、调度、执行和提交；内存系统让多个核心与设备看到一组受约束的共享状态。

## 阅读路径

### 软件可见边界

- [ISA 与微架构](isa-microarchitecture.md)：为什么相同二进制可在结构完全不同的处理器上运行。
- [虚拟内存与 TLB](virtual-memory-tlb.md)：地址翻译、保护和缓存怎样进入每一次内存访问。
- [原子与内存模型](atomics-memory-model.md)：语言、编译器、ISA 与一致性协议如何共同建立跨线程顺序。

### 单核执行

- [流水线、ILP 与分支预测](pipeline-ilp-branch.md)：前端、乱序窗口、执行端口和提交如何隐藏延迟。
- [CPU](cpu.md)：核心、SMT、NUMA、向量与性能计数器如何组合成现代通用处理器。

### 多核与加速器

- [缓存与一致性](cache-coherence.md)：私有缓存怎样在共享内存抽象下协作，以及 false sharing 为何昂贵。
- [GPU 与 SIMT](gpu-simt.md)：吞吐导向处理器怎样用大量线程、分层存储和掩码执行隐藏延迟。

## 契约不能混用

| 问题 | 应查看的层次 | 典型误区 |
| --- | --- | --- |
| 某指令是否合法、异常如何报告 | ISA/ABI | 用某款 CPU 行为代表整个 ISA |
| 两条指令能否同时执行 | 微架构 | 从反汇编直接推断周期数 |
| 两个核心何时看见写入 | 语言内存模型 + ISA + 一致性 | 把 cache coherence 当顺序一致性 |
| 虚拟地址为何突然变慢 | TLB + 页表 + OS | 把 TLB miss 当 page fault |
| GPU kernel 为何低效 | SIMT + 存储层次 + 调度 | 只看 occupancy 或峰值 FLOPS |

## 从程序到提交

一次典型 CPU 指令经历：

$$
\text{fetch}\rightarrow\text{decode}\rightarrow\text{rename}\rightarrow
\text{dispatch}\rightarrow\text{issue}\rightarrow\text{execute}\rightarrow
\text{retire}
$$

中间可以乱序，架构状态通常按程序顺序提交。load/store 还会经过地址生成、TLB、缓存、一致性和内存控制器。异常必须表现为精确状态，错误预测和未提交的推测结果需要被丢弃。

GPU 走不同路线：它以大量可运行 warp 覆盖延迟，让共同控制流下的多线程成批发射。两者并不是“复杂 CPU 对简单 GPU”的固定二分；现代 GPU 同样有复杂调度、缓存与地址翻译，现代 CPU 也具有宽 SIMD 和大量并行执行资源。

## 量化视角

硬件峰值只是上界。计算吞吐受执行单元、指令混合和依赖限制；内存吞吐受请求并行度、地址模式与通道限制；实际性能大致受较紧的上界约束：

$$
P\le\min(P_\mathrm{compute}, I\cdot B_\mathrm{memory})
$$

$I$ 是运算强度，表示每搬运一个字节完成多少运算。这个 roofline 视角适合先判断“优化计算还是数据移动”，再进入具体微架构。

## Reference

- [RISC-V Ratified Specifications Library](https://docs.riscv.org/reference/home/index.html)
- [Intel 64 and IA-32 Architectures Software Developer Manuals](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html)
- [Arm Architecture Reference Manuals](https://developer.arm.com/Architectures)
- [NVIDIA CUDA Programming Guide](https://docs.nvidia.com/cuda/cuda-programming-guide/)
- [Computer Architecture: A Quantitative Approach, 6th Edition](https://www.elsevier.com/books/computer-architecture/hennessy/978-0-12-811905-1)
