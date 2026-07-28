# GPU 与 SIMT

GPU 把更多晶体管投入大量算术通道和线程状态，通过并发 warp 在一个 warp 等待内存时发射另一个 warp，以吞吐换取延迟隐藏。SIMT 让程序写成许多标量线程，同时让硬件成组执行这些线程。

本文以 NVIDIA CUDA Programming Guide 13.2（核验至 2026-07-28）的公开编程模型为具体坐标；AMD wavefront、Apple SIMD-group 和其他 GPU 在术语、宽度、存储层次与同步范围上不同。

## 线程层次

CUDA kernel 启动为 grid，grid 包含 thread block，block 包含 thread。线程通过 `threadIdx`、`blockIdx` 和维度计算全局索引。

```text
grid
├── block 0 ── threads 0..N-1
├── block 1 ── threads 0..N-1
└── ...
```

block 是关键调度与协作边界：

- 一个 block 驻留在一个 SM 上；
- 同 block 线程可通过 shared memory 协作；
- `__syncthreads()` 只同步该 block；
- block 之间通常必须通过 kernel 边界、cooperative groups 或其他明确机制同步。

设计 grid 时应允许 block 独立调度，不能依赖普通 kernel 中“block 0 一定先于 block 1”。

## warp 与 SIMT

CUDA 将相邻线程组成 32 线程 warp。编程模型允许每个线程有独立控制流；硬件以活跃掩码执行 warp 的共同指令。

### divergence

同一 warp 内线程走不同分支时，执行资源需要覆盖各活跃路径，未参与路径的 lane 被屏蔽：

$$
\eta_\mathrm{branch}\approx
\frac{\text{active lane-instructions}}
{\text{issued lane capacity}}
$$

短分支可能被 predication，复杂分支则分路径执行。分歧只在 warp 内直接造成 lane 浪费；不同 warp 走不同路径本身没有同样问题。

Volta 及以后支持 Independent Thread Scheduling，但这不授权依赖隐式 warp 同步。需要 warp 内通信时，应使用带 mask 的同步原语并满足 CUDA 文档要求。

## 存储层次

| 空间 | 典型作用域 | 主要特征 |
| --- | --- | --- |
| register | thread | 最低延迟；过多会降低驻留或 spill |
| local memory | thread 的地址空间 | 名称虽 local，通常落在设备内存层次 |
| shared memory | block | 软件管理、低延迟、分 bank |
| L1/L2 cache | SM / device | 硬件管理，具体共享关系依架构 |
| global memory | device | 容量大、延迟高，需要合并访问与并发 |
| constant/texture | 特定只读模式 | 广播或空间局部性优化，规则依接口 |

“变量声明在函数内”不保证放寄存器；数组动态索引、寄存器压力或编译器选择都可能造成 spill。

## 合并访问

warp 的 global memory 请求会按地址分布合并成若干内存事务。相邻线程访问相邻且对齐的数据通常最有效：

```cpp
std::size_t i = blockIdx.x * blockDim.x + threadIdx.x;
out[i] = a[i] + b[i];
```

若线程按大 stride 访问，事务中有效字节比例下降。AoS 与 SoA 的选择要围绕“一个 warp 同时读哪些字段”判断。

shared memory 又有 bank 映射。多个线程访问同一 bank 的不同地址可能串行；广播和现代硬件的具体规则应查对应 compute capability 文档。

## 一个完整 CUDA kernel

下面的 CUDA C++17 例子执行向量加法并检查异步错误。适用于 CUDA Toolkit 13.2；真实程序还应选择流、分配策略和批处理边界。

```cuda
#include <cuda_runtime.h>
#include <cstddef>
#include <cstdlib>
#include <iostream>
#define CUDA_OK(x) do { cudaError_t e = (x); if (e != cudaSuccess) { \
    std::cerr << cudaGetErrorString(e) << '\n'; std::exit(1); } } while (0)
__global__ void add(const float* a, const float* b, float* c, std::size_t n) {
    std::size_t i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) c[i] = a[i] + b[i];
}
int main() {
    constexpr std::size_t n = 1 << 20, bytes = n * sizeof(float);
    float *a, *b, *c;
    CUDA_OK(cudaMallocManaged(&a, bytes));
    CUDA_OK(cudaMallocManaged(&b, bytes));
    CUDA_OK(cudaMallocManaged(&c, bytes));
    for (std::size_t i = 0; i < n; ++i) { a[i] = 1; b[i] = 2; }
    add<<<(n + 255) / 256, 256>>>(a, b, c, n);
    CUDA_OK(cudaGetLastError());
    CUDA_OK(cudaDeviceSynchronize());
    std::cout << c[n / 2] << '\n';
    CUDA_OK(cudaFree(a)); CUDA_OK(cudaFree(b)); CUDA_OK(cudaFree(c));
}
```

编译：

```bash
nvcc -O3 -std=c++17 add.cu -o add
```

Unified Memory 简化示例，却可能产生页迁移。测 kernel 本体应使用 CUDA events，并明确是否包含 H2D/D2H 传输、首次 page fault、JIT 和同步。

## latency hiding 与 occupancy

一个 SM 可驻留的 block/warp 数受：

- 每 block 线程数；
- 每线程寄存器；
- 每 block shared memory；
- 架构上限；
- barrier 和执行资源。

occupancy 是实际驻留 warp 与理论上限之比。更高 occupancy 提供更多可切换 warp，但并非单调提高性能：增加 spill、减少每线程工作或牺牲数据重用，可能让高 occupancy 更慢。

真正问题是：当一个 warp 因依赖或内存等待时，是否有足够的 eligible warp，以及瓶颈在发射、算术、内存还是同步。

## tiled 协作

矩阵乘法等操作可让 block 把 global memory tile 搬入 shared memory，多次复用后再加载下一 tile：

$$
C_{ij}=\sum_k A_{ik}B_{kj}
$$

tiling 提高运算强度，但引入：

- tile 边界处理；
- shared memory 容量与 bank conflict；
- register pressure；
- block 同步；
- 异步拷贝与流水级协调。

生产代码通常使用经过调优的库；手写 kernel 的价值在于理解数据移动，而不是替代所有 BLAS 实现。

## 原子、同步与可见性

- `__syncthreads()` 是 block barrier，并包含规定范围的内存可见性；
- warp 原语需要正确 active mask；
- device/global 原子具有自己的 scope 与 ordering；
- stream 内操作按 CUDA 规则排序，不同 stream 可并发；
- kernel launch 对 host 通常异步，错误也可能延迟到同步点报告。

CPU 的 C++ 内存模型不能直接描述所有 device/host 交互；使用 CUDA 定义的原子、stream、event 与同步 API。

## CPU—GPU 数据路径

端到端时间应写成：

$$
T=T_\mathrm{prepare}+T_\mathrm{H2D}+T_\mathrm{kernel}
+T_\mathrm{D2H}+T_\mathrm{sync}
$$

小 kernel 可能被 launch 和传输成本主导。改进方向包括批处理、常驻数据、pinned memory、异步 copy、多个 stream 和 kernel fusion，但每种方式都会增加生命周期与背压管理。

Unified Memory 不是“没有传输”，而是由运行时和驱动按访问迁移或映射页面。访问模式不佳时 page thrashing 会严重拖慢。

## 测量方法

1. 用 CUDA event 测 GPU 时间，用 host 单调时钟测端到端；
2. 热身并隔离首次 context/JIT；
3. 报告 GPU 型号、驱动、Toolkit、compute capability、时钟与功耗；
4. 用 Nsight Systems 看 CPU、copy、kernel 时间线；
5. 用 Nsight Compute 检查 memory throughput、warp stall、occupancy 和指令；
6. 通过改变 tile、block、数据布局构造因果对照；
7. 同时校验数值结果与精度。

## 失败模式

- 只计 kernel、不计必要传输和同步；
- 把线程数当真正同时执行的 lane 数；
- 分支跨 warp 不同却误判为 warp divergence；
- 追求 occupancy 导致 register spill；
- 忘记 kernel launch 异步，计时几乎为零；
- 依赖旧架构的隐式 warp 同步；
- 访问未合并、shared bank conflict，却只优化 FLOPS；
- 从 NVIDIA 的 warp=32 推广到所有 GPU；
- 把峰值 Tensor Core 吞吐与任意精度、任意形状的应用性能等同。

## 跨层连接

- 数据布局与局部性见 [数据表示与内存层次](../foundations/data-memory-hierarchy.md)；
- CPU 侧提交、线程与 NUMA 放置见 [CPU](cpu.md)；
- GPU 页迁移和统一地址进入 [虚拟内存](virtual-memory-tlb.md)；
- device DMA 与完成通知进入 [I/O、中断与 DMA](../os/io-interrupt-dma.md)；
- GPU 专用模型训练和推理实现属于相邻知识域，本页只建立通用系统基础。

## Reference

- [NVIDIA CUDA Programming Guide](https://docs.nvidia.com/cuda/cuda-programming-guide/)
- [NVIDIA CUDA Runtime API](https://docs.nvidia.com/cuda/cuda-runtime-api/)
- [NVIDIA Nsight Compute Documentation](https://docs.nvidia.com/nsight-compute/)
- [AMD HIP Programming Manual](https://rocm.docs.amd.com/projects/HIP/en/latest/)
- [AMD CDNA Architecture](https://www.amd.com/en/technologies/cdna.html)
- [Kirk and Hwu, Programming Massively Parallel Processors, 4th Edition](https://www.elsevier.com/books/programming-massively-parallel-processors/kirk/978-0-323-91231-0)
- [Linux Heterogeneous Memory Management](https://www.kernel.org/doc/html/latest/mm/hmm.html)
