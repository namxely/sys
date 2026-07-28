# SIMD 与 SIMT

SIMD 和 SIMT 都把同一条指令应用到多个 lane，但暴露给程序员的抽象不同。SIMD 指令显式操作向量寄存器；SIMT 让程序写许多标量线程，硬件以 warp/wavefront 成组发射。

<a id="simd"></a>
## SIMD：显式向量

若向量宽度为 $W$，理想循环每条向量指令处理 $W$ 个元素。编译器向量化要求识别无冲突迭代、对齐和别名。`restrict`/语言别名信息、连续布局和简单控制流可帮助证明。

尾部长度 $n\bmod W$ 可用 scalar epilogue 或 masked vector 处理。性能不只看向量宽度：

$$
T\ge\max\left(
\frac{\text{vector instructions}}{\text{issue throughput}},
\frac{\text{bytes}}{\text{memory bandwidth}},
\text{dependency latency}
\right)
$$

AoS 到 SoA 的变换常让同一字段连续，减少 gather；但对象整体访问时可能相反，应由真实访问模式决定。

<a id="simt"></a>
## SIMT：线程束与 active mask

GPU 将相邻 thread ID 组成 warp。warp 内线程执行相同指令，但各自有寄存器、程序计数状态和数据。分支时 active mask 选择参与线程；若同一 warp 走多个路径，路径需分别执行：

$$
\mathrm{branch\ efficiency}
\approx\frac{\text{active lane-instructions}}
{\text{issued lane-instructions}}
$$

分歧只在 warp 内重要。把相似控制流数据聚在一起、用 predication 或重排工作可降低损失，但重排本身有成本。

<a id="memory"></a>
## 合并访问与 bank conflict

连续线程访问连续全局地址时，硬件可合并为少量 memory transaction。若 stride 大或地址离散，请求会放大。共享内存分为 banks；同一 warp 对不同地址但同 bank 的访问可能串行，广播等特例除外。

访问模式分析应画出：

```text
lane:       0   1   2   3  ...
address:    a  a+4 a+8 a+12 ...
cacheline:  [-----------]
```

对矩阵转置，tile 到 shared memory 并 padding 一列可同时改善 global coalescing 与 shared bank conflict。

<a id="reduction"></a>
## 归约与扫描

树形归约 span 为 $O(\log n)$。warp shuffle 可在线程寄存器间交换数据，避免部分 shared memory 和 barrier：

```cuda
__device__ float warp_sum(float x) {
    unsigned mask = __activemask();
    for (int d = warpSize / 2; d; d >>= 1)
        x += __shfl_down_sync(mask, x, d);
    return x;
}
```

这段代码只在参与 lane 组成预期归约集合时正确；部分 warp、非连续 active mask 或跨 warp 归约需额外设计。浮点结合顺序改变仍存在数值差异。

<a id="portability"></a>
## 可移植思维

- 用算法表达数据并行，用平台机制实现 lane/warp。
- 把向量宽度、warp size 和 memory transaction 粒度视为查询到的参数。
- 正确性不依赖隐式 lockstep；需要同步时使用语言定义原语。
- 为 scalar、SIMD、GPU 路径建立相同测试 oracle 与误差容限。

## 测量

CPU 观察 vector instruction mix、cycles、cache misses 和编译器 vectorization report；GPU 观察 warp execution efficiency、branch divergence、global load efficiency、bank conflicts、occupancy 与 stall reason。单一“occupancy 100%”不能证明 kernel 高效。

## 从 lane 扩展出去

- [Work、Span 与扩展定律](performance-models.md)给出算术强度、带宽上界与并行效率的统一模型。
- [CUDA 编程模型](cuda.md)把 warp、shared memory 与 coalescing 落到完整 kernel。
- [共享内存与 OpenMP](shared-memory-openmp.md) 连接 CPU 线程、cache coherence、NUMA 与向量化。

## Reference

- [Intel 64 and IA-32 Architectures Software Developer Manuals](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html)
- [Arm Architecture Reference Manuals](https://developer.arm.com/Architectures)
- [RISC-V Unprivileged ISA: V Vector Extension](https://docs.riscv.org/reference/isa/unpriv/v-st-ext)
- [CUDA Programming Guide: Basics of SIMT](https://docs.nvidia.com/cuda/cuda-programming-guide/02-basics/writing-cuda-kernels.html#basics-of-simt)
- [CUDA Best Practices Guide: Device Memory Spaces](https://docs.nvidia.com/cuda/cuda-c-best-practices-guide/index.html#device-memory-spaces)
