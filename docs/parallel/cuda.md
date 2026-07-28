# CUDA 编程模型

CUDA 程序由 host code 和 device kernels 组成。kernel 启动一个 grid，grid 包含 blocks，block 包含 threads。block 是调度与协作边界：同一 block 线程能用 shared memory 和 block barrier；不同 block 默认不能依赖同时驻留。

<a id="hierarchy"></a>
## Grid、Block 与 Thread

一维索引：

```cuda
__global__ void saxpy(float a, const float *x, float *y, size_t n) {
    size_t i = (size_t)blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) y[i] = a * x[i] + y[i];
}
```

grid-stride loop 让固定 grid 处理任意长度并改善复用：

```cuda
for (size_t i = (size_t)blockIdx.x * blockDim.x + threadIdx.x;
     i < n; i += (size_t)blockDim.x * gridDim.x) {
    y[i] = a * x[i] + y[i];
}
```

block size 需在 warp 整数倍、寄存器、shared memory、occupancy 与每线程工作之间平衡，不存在通用“256 一定最佳”。

<a id="memory-hierarchy"></a>
## 内存层次与 tile

| 空间 | 可见范围 | 生命周期 | 典型用途 |
| --- | --- | --- | --- |
| register | thread | thread | 标量与小局部状态 |
| local | thread | kernel | register spill、局部数组，物理上在 device memory |
| shared | block | block | 可编程 tile/cache、协作 |
| global | device/grid | allocation | 主数据 |
| constant/texture | device | allocation | 特殊只读访问模式 |

矩阵乘 tile 的目标是让从 global 读取的元素在 block 内复用，提高 arithmetic intensity。shared memory 写入后必须在消费者前 `__syncthreads()`；所有活跃线程必须以一致方式到达 barrier，否则可能死锁。

<a id="async"></a>
## Stream、异步与重叠

同一 stream 中操作按定义顺序执行；不同 stream 可并发，但是否真正重叠取决于依赖、引擎和资源。异步 host-device copy 通常需要 pinned host memory。event 可表达设备时间点和跨 stream 依赖。

错误检查要覆盖 launch 与异步完成：

```cpp
#define CUDA_OK(x) do { cudaError_t e = (x); if (e != cudaSuccess) { \
    std::fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, cudaGetErrorString(e)); \
    std::exit(EXIT_FAILURE); } } while (0)

saxpy<<<grid, block, 0, stream>>>(a, x, y, n);
CUDA_OK(cudaGetLastError());
CUDA_OK(cudaStreamSynchronize(stream));
```

只检查 `cudaGetLastError()` 能发现 launch configuration 等即时错误，不能替代同步点暴露的执行错误。

<a id="occupancy"></a>
## Occupancy 不是性能

SM 上 resident blocks 受 threads、registers、shared memory 和架构上限约束。occupancy 提供隐藏 latency 的 warps，但高 occupancy 可能以 register spill 和额外 local-memory traffic 为代价。

Roofline 仍是第一判断：

$$
P\le \min(P_{\max},BW\cdot I)
$$

memory-bound kernel 应先看 coalescing、bytes 与复用；compute-bound 再看指令 mix、tensor core、依赖与 pipeline。

<a id="correctness"></a>
## 并发与数值正确性

- `__syncthreads` 只覆盖 block；跨 block 需分 kernel、cooperative groups 或原子协议。
- atomic 保证特定地址操作原子，不自动保证整个结构不变量。
- device memory model 有 scope/order；用匹配的 atomic/fence，而非依赖经验上的执行顺序。
- racecheck 工具不能证明无 race，只能发现被执行路径中的问题。
- 浮点并行归约次序改变，应定义容差和稳定算法。

## 性能实践

1. Nsight Systems 看 host/device timeline、copy、空隙和同步。
2. Nsight Compute 看单 kernel 的 memory transactions、occupancy、stall 与 roofline。
3. 先确保结果正确，再逐项改变布局、block、tile 和 stream。
4. 测量时排除首次 context/JIT、固定 clocks 与功耗条件，并报告 GPU、driver、toolkit。

## 把 kernel 放回系统

- [SIMD 与 SIMT](simd-simt.md) 解释 lane、warp、分歧与合并访问的执行基础。
- [Work、Span 与扩展定律](performance-models.md)提供 Roofline、并行度与负载均衡的上界。
- [拓扑与通信优化](topology-communication.md)把多 GPU、PCIe、NVLink、NUMA 与 NIC 放置接到 kernel 之外。

## Reference

- [CUDA Programming Guide](https://docs.nvidia.com/cuda/cuda-programming-guide/)
- [CUDA Runtime API](https://docs.nvidia.com/cuda/cuda-runtime-api/)
- [CUDA Best Practices Guide](https://docs.nvidia.com/cuda/cuda-c-best-practices-guide/)
- [CUDA C++ Memory Model](https://docs.nvidia.com/cuda/cuda-programming-guide/05-appendices/cuda-cpp-memory-model.html#cuda-cplusplus-memory-model)
- [Nsight Systems User Guide](https://docs.nvidia.com/nsight-systems/UserGuide/)
- [Nsight Compute Profiling Guide](https://docs.nvidia.com/nsight-compute/ProfilingGuide/)
