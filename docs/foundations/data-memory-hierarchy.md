# 数据表示与内存层次

处理器只搬运和变换比特；类型、对象、字符、地址和指令都是软件赋予这些比特的解释。性能问题则来自另一个事实：存储容量越大，通常离执行单元越远、延迟越高。数据表示决定“搬什么”，内存层次决定“要等多久”。

## 比特没有天然类型

同一串 `0x3f800000` 可以被解释为整数 `1065353216`，也可以按 IEEE 754 binary32 解释为浮点数 $1.0$。合法解释受语言对象模型约束，不能仅因位模式相同就用不兼容指针解引用。

### 无符号与补码

对 $w$ 位无符号整数：

$$
U(b)=\sum_{i=0}^{w-1}b_i2^i
$$

补码整数的最高位权重为负：

$$
T(b)=-b_{w-1}2^{w-1}+\sum_{i=0}^{w-2}b_i2^i
$$

无符号运算按模 $2^w$ 进行。C++20 起标准以补码描述有符号整数表示，但有符号溢出仍是未定义行为；编译器可据此消除看似合理的溢出检查。需要模运算时应使用无符号类型或显式溢出原语。

### 浮点数是分段编码

IEEE 754 binary32 由 1 位符号、8 位阶码和 23 位尾数组成。正规数近似为：

$$
x=(-1)^s(1.f)_2\,2^{e-\mathrm{bias}}
$$

它还编码次正规数、$\pm0$、$\pm\infty$ 与 NaN。浮点加法不满足数学实数的结合律，因为每一步都会舍入：

$$
\operatorname{fl}(\operatorname{fl}(a+b)+c)\ne
\operatorname{fl}(a+\operatorname{fl}(b+c))
$$

并行归约改变求和树，因此最后几位不同不一定是并发错误；但算法仍应界定可接受误差并固定舍入模式、精度与硬件边界。

## 字节序、对齐与对象布局

字节序决定多字节标量的字节排列，不决定字符串或单字节数组的顺序。网络协议通常明确线格式；内存中的结构体则还包含对齐填充、ABI 和编译器布局规则，不能直接 `send(sizeof(struct))` 当作协议。

下面的 C++23 代码从固定小端字节序解码 32 位整数，不依赖主机字节序，也避免未对齐解引用和严格别名问题：

```cpp
#include <bit>
#include <cstdint>
#include <cstring>
#include <span>
std::uint32_t load_le32(std::span<const std::byte, 4> in) {
    std::uint32_t x;
    std::memcpy(&x, in.data(), sizeof x);
    if constexpr (std::endian::native == std::endian::big) x = std::byteswap(x);
    return x;
}
```

若格式跨语言、跨版本或落盘，还要固定字段宽度、符号、字节序、对齐、可选字段与校验方式。内存布局是实现细节，序列化格式才是长期契约。

## 地址不是普通整数

虚拟地址先由 [页表与 TLB](../architecture/virtual-memory-tlb.md) 翻译，再访问缓存或内存。语言中的指针还携带对象生命周期与 provenance 约束。把指针转为整数再随意运算，即使数值回到原地址，也不自动恢复合法对象访问。

现代系统还可能在地址高位编码标签、权限或地址空间信息。写系统代码时应优先使用标准指针运算和平台公开 API，避免依赖“地址就是无符号 64 位整数”的偶然事实。

## 内存层次为何有效

<figure class="sys-figure" id="memory-hierarchy">
  <a class="sys-figure__media" href="../../assets/figures/memory-hierarchy.svg">
    <img src="../../assets/figures/memory-hierarchy.svg" alt="从寄存器、处理器缓存、DRAM 到 SSD 的容量、持久性、延迟和管理粒度层次" width="1200" height="600" loading="lazy">
  </a>
  <figcaption>越靠近执行单元的层次通常越小、越快、管理粒度越细；局部性决定上层请求能否被更快层吸收。示意图依据 <a href="https://csapp.cs.cmu.edu/">CS:APP 的存储器层次</a>与 <a href="https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html">Intel 体系结构手册</a>重新绘制。</figcaption>
</figure>

程序常具有：

- **时间局部性**：刚访问的数据近期可能再次访问；
- **空间局部性**：访问某地址后，邻近地址更可能被访问；
- **顺序局部性**：指令和流式数据呈可预测推进；
- **工作集局部性**：某阶段反复访问相对稳定的数据集合。

缓存以固定大小的 cache line 为传输与一致性单位。一次 miss 不只取一个变量，而是取整条 line；顺序扫描因而能利用空间局部性，随机指针追逐则常形成串行 miss。

### 平均访问时间

两级简化模型可写为：

$$
\mathrm{AMAT}=t_{L1}+m_{L1}(t_{L2}+m_{L2}t_\mathrm{mem})
$$

$t$ 是命中或访问成本，$m$ 是 miss rate。真实处理器可以让多个 miss 重叠、预取后续 line、合并 store，因此 AMAT 更适合解释依赖式访问，而不是直接预测所有程序时间。

### 容量、冲突与一致性 miss

- 容量 miss：活跃工作集超过缓存容量；
- 冲突 miss：多个地址映射到有限组，虽有总空间仍互相驱逐；
- compulsory miss：首次触及尚未装入；
- coherence miss：其他核心写入使本地副本失效。

分类是诊断语言，不一定能由单个硬件事件直接精确计数。

## 缓存行与数据布局

数组结构（AoS）便于按对象访问；结构数组（SoA）便于只扫描少数字段和向量化。选择取决于访问模式：

```cpp
struct ParticleAoS { float x, y, z, mass; };
struct ParticlesSoA {
    std::vector<float> x, y, z, mass;
};
```

若循环只计算 `x[i] += vx[i] * dt`，SoA 减少无关字段流量；若每次都消费单个粒子的全部字段，AoS 可能更自然。不要凭风格决定，应用工作集、SIMD 宽度与 cache miss 数据才是证据。

### false sharing

两个线程修改不同变量，如果变量位于同一一致性 line，所有权仍会在核心间来回转移。可用 `std::hardware_destructive_interference_size` 表达实现建议的隔离粒度：

```cpp
#include <atomic>
#include <cstdint>
#include <new>
struct alignas(std::hardware_destructive_interference_size) Counter {
    std::atomic<std::uint64_t> value{0};
};
```

该常量是 C++17 的实现属性，不是所有 CPU 上 cache line 大小的运行时查询。过度填充也会扩大工作集和 TLB 压力，应测量后使用。

## 从缓存到 DRAM

最后级缓存 miss 进入内存控制器队列。DRAM 访问还涉及通道、rank、bank、row buffer、刷新与调度。连续地址通常更容易形成突发传输；多通道带宽只有在请求并行度足够时才能利用。

在 NUMA 系统中，物理页的归属节点决定本地或远端访问。线程首次触页、内核迁页策略和线程迁移会共同改变结果。仅绑定线程但不控制内存放置，或仅 `numactl --membind` 却允许线程迁移，都可能让实验失真。

## 测量局部性：依赖式指针追逐

下面的 C++20 程序把数组打乱成单一环，后一次加载依赖前一次结果，减少硬件并行覆盖延迟的能力。它适合观察容量跨越时的相对台阶，不是“精确测某级缓存延迟”的通用仪器。

```cpp
#include <algorithm>
#include <chrono>
#include <cstddef>
#include <iostream>
#include <numeric>
#include <random>
#include <string>
#include <vector>
int main(int argc, char** argv) {
    std::size_t n = argc > 1 ? std::stoull(argv[1]) / sizeof(std::size_t) : 1 << 20;
    std::vector<std::size_t> order(n), next(n);
    std::iota(order.begin(), order.end(), 0);
    std::mt19937_64 rng(1);
    std::shuffle(order.begin(), order.end(), rng);
    for (std::size_t i = 0; i < n; ++i) next[order[i]] = order[(i + 1) % n];
    std::size_t p = order[0], steps = n * 32;
    auto t0 = std::chrono::steady_clock::now();
    for (std::size_t i = 0; i < steps; ++i) p = next[p];
    auto t1 = std::chrono::steady_clock::now();
    std::cout << p << ' ' << std::chrono::duration<double, std::nano>(t1 - t0).count() / steps << '\n';
}
```

实验时对多种 $n$ 重复运行，固定 CPU，记录 huge page、频率、NUMA 和编译器设置，并结合 `cycles`、cache miss、TLB miss 事件。预取器、替换策略和随机排列都会影响曲线，不能只凭一个台阶命名具体层级。

## 常见错误

- 用 `reinterpret_cast` 绕过对象模型，产生未定义行为；
- 认为 `volatile` 能提供线程同步；它不建立 C++ happens-before；
- 把 `sizeof(T)` 当稳定网络或磁盘格式；
- 只按大 O 分析，忽略每元素字节数和访问顺序；
- 把 cache line、页大小、SIMD 宽度写死为某个平台的数值；
- 只看 cache miss 比例，不看总访问数、重叠程度和最终 stall；
- 在虚拟机、容器或共享主机上测量，却不记录宿主资源干扰。

## 跨层连接

- 数据布局影响 [流水线、ILP 与分支预测](../architecture/pipeline-ilp-branch.md) 的向量化和前端压力；
- cache line 同时是 [缓存一致性](../architecture/cache-coherence.md) 的基本粒度；
- 页大小与访问模式共同决定 [TLB](../architecture/virtual-memory-tlb.md) 覆盖；
- 编译器与 CPU 重排必须服从 [原子与内存模型](../architecture/atomics-memory-model.md)；
- 文件映射页还受 [操作系统虚拟内存](../os/virtual-memory.md) 和 [文件系统](../os/filesystem.md) 回写策略影响。

## Reference

- [Computer Systems: A Programmer's Perspective](https://csapp.cs.cmu.edu/)
- [IEEE 754-2019 Standard for Floating-Point Arithmetic](https://standards.ieee.org/ieee/754/6210/)
- [ISO C++ working draft: basic types](https://eel.is/c++draft/basic.types)
- [ISO C++ working draft: object representation and lifetime](https://eel.is/c++draft/basic.memobj)
- [RISC-V Unprivileged ISA Specification](https://docs.riscv.org/reference/isa/unpriv/unpriv-index.html)
- [Intel 64 and IA-32 Architectures Optimization Reference Manual](https://www.intel.com/content/www/us/en/developer/articles/technical/intel64-and-ia32-architectures-optimization.html)
- [Intel 64 and IA-32 Architectures Software Developer Manuals](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html)
- [Linux NUMA Memory Policy](https://www.kernel.org/doc/html/latest/admin-guide/mm/numa_memory_policy.html)
- [Ulrich Drepper, What Every Programmer Should Know About Memory](https://www.akkadia.org/drepper/cpumemory.pdf)
