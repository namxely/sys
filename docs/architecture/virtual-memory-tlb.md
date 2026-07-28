# 虚拟内存与 TLB

程序发出的地址通常是虚拟地址。MMU 根据当前地址空间的页表把虚拟页号翻译成物理页框号，同时检查读、写、执行和特权权限。TLB 缓存近期翻译，使大多数访问不必重新遍历页表。

## 地址翻译的基本分解

页大小为 $2^p$ 字节时：

$$
\mathrm{VA}=\mathrm{VPN}\cdot 2^p+\mathrm{offset}
$$

页表把 VPN 映射到 PFN，页内偏移保持不变：

$$
\mathrm{PA}=\mathrm{PFN}\cdot 2^p+\mathrm{offset}
$$

映射还附带 present、read/write、user/supervisor、execute-disable、accessed、dirty 等属性。具体位定义属于 ISA；Linux 的通用页表层级会折叠到目标架构实际支持的层数。

## 多级页表为何存在

线性页表要为整个虚拟地址空间保留条目，大量未映射空洞会浪费内存。多级页表按需分配下层页面：高层条目为空时，整片地址范围无需继续展开。

以每级索引 $b$ 位、页内偏移 $p$ 位、共 $k$ 级为抽象模型：

$$
\mathrm{VA\ bits}=kb+p
$$

一次最坏 page walk 可能读取多个页表层级，最后才读取数据。硬件 page-walk cache、并行查找和 cache 层次可以降低成本，但依赖式 TLB miss 仍很昂贵。

## TLB 不是页缓存

| 事件 | 缺少什么 | 由谁处理 | 是否一定进入内核 |
| --- | --- | --- | --- |
| cache miss | 数据 cache line | cache/内存系统 | 否 |
| TLB miss | 地址翻译 | 硬件或软件 page walker | 否 |
| page fault | 有效映射/权限/驻留页 | CPU trap + 内核 | 是 |
| major fault | 所需页不驻留，需从文件系统或 swap 等后备存储读入 | 内核 + I/O | 是 |

TLB miss 可由硬件走页表后完成，不等于 page fault。minor fault 也不一定访问磁盘，例如首次匿名页、copy-on-write 或已在 page cache 的文件页。

## TLB reach

若某级 TLB 有 $E$ 个有效条目、每项覆盖 $P$ 字节，理想覆盖范围为：

$$
\mathrm{reach}=E\cdot P
$$

关联度、不同页大小分区、地址空间标签和访问冲突会使实际覆盖更复杂。huge page 能扩大 reach、减少页表内存和 walk 次数，却会增加内部碎片、连续物理内存压力和回收/迁移成本。

## ASID、PCID 与上下文切换

切换进程时页表根改变。若 TLB 条目只按 VPN 标识，就必须大量失效。ASID（Arm/RISC-V 常用术语）或 PCID（x86）给翻译附加地址空间标签，使不同进程条目可共存。

标签数量有限，重用时仍需失效；权限变化、unmap、copy-on-write 和页迁移还可能触发跨 CPU TLB shootdown。shootdown 需要通知正在使用该地址空间的核心，是频繁映射变更的扩展性成本。

## VIPT cache 与别名

cache 可在翻译完成前用虚拟页内偏移索引，以并行 TLB 查找；tag 最终用物理地址比较。若索引位超出页内偏移，同一物理页的不同虚拟别名可能落入不同组，硬件或 OS 必须处理 synonym。

这说明页大小、L1 容量和关联度并非完全独立。软件通常不直接处理 VIPT 细节，但 JIT、共享映射、I-cache 同步和特殊内核映射会碰到相关边界。

## 权限与访问位

页表不只是地址字典：

- NX/XD 阻止数据页执行；
- user/supervisor 阻止用户访问内核映射；
- read-only 支持代码保护与 copy-on-write；
- accessed/dirty 位帮助 OS 估计使用和回写；
- memory type 控制普通缓存、设备内存等访问属性。

修改 PTE 后必须按 ISA 与内核协议完成 cache/TLB 同步。直接写页表但遗漏 barrier 或 shootdown，会出现某些核心继续使用旧权限的严重错误。

## 一个 TLB 压力实验

下面的 Linux/C++20 程序每页只触碰一个字节，并随机遍历页面。它混合了 TLB、page walk、cache 和 DRAM 影响，适合比较页数增长的转折，不适合把结果直接命名为“TLB latency”。

```cpp
#include <algorithm>
#include <chrono>
#include <cstddef>
#include <iostream>
#include <numeric>
#include <random>
#include <string>
#include <sys/mman.h>
#include <unistd.h>
#include <vector>
int main(int argc, char** argv) {
    std::size_t pages = argc > 1 ? std::stoull(argv[1]) : 65536;
    std::size_t ps = static_cast<std::size_t>(::sysconf(_SC_PAGESIZE));
    auto* p = static_cast<unsigned char*>(::mmap(nullptr, pages * ps, PROT_READ | PROT_WRITE,
        MAP_PRIVATE | MAP_ANONYMOUS, -1, 0));
    if (p == MAP_FAILED) return 1;
    std::vector<std::size_t> order(pages);
    std::iota(order.begin(), order.end(), 0);
    std::shuffle(order.begin(), order.end(), std::mt19937_64{1});
    for (auto i : order) p[i * ps] = 1;
    volatile unsigned sum = 0;
    auto t0 = std::chrono::steady_clock::now();
    for (int r = 0; r < 64; ++r) for (auto i : order) sum += p[i * ps];
    auto ns = std::chrono::duration<double, std::nano>(std::chrono::steady_clock::now() - t0).count();
    std::cout << sum << ' ' << ns / (pages * 64) << '\n';
    ::munmap(p, pages * ps);
}
```

编译器会警告对 `volatile` 复合赋值；这里仅用它保留测量结果，不用于并发同步。测量时可配合目标 CPU 的 `dTLB-load-misses`、page-walk 事件以及 `/proc/vmstat`；事件名必须经 `perf list` 核实。

## page size 的权衡

| 选择 | 主要收益 | 主要代价 |
| --- | --- | --- |
| 小页 | 碎片少、按页保护细 | TLB reach 小、页表大 |
| 显式 huge page | 可预测的覆盖与锁定策略 | 预留和部署复杂 |
| transparent huge page | 应用改动少 | collapse/拆分延迟与策略波动 |
| 混合页大小 | 适配不同区域 | TLB 分区和诊断更复杂 |

对稀疏访问或生命周期短的小对象，huge page 可能浪费内存；对长期顺序扫描的大数组，常更有价值。应同时测 CPU 时间、fault、TLB miss、RSS 与尾延迟。

## 失败模式

- 把 TLB miss、page fault 和 cache miss 混为一谈；
- 仅用工作集字节数预测 TLB，忽略页数和访问分布；
- 更改映射权限后遗漏 TLB shootdown 或指令 cache 同步；
- 把 4 KiB、2 MiB 等常见大小当跨平台常量；
- 开启 THP 后只看平均吞吐，忽略 collapse 导致的长尾；
- 线程绑核却不控制 NUMA 页放置；
- 用 `/proc/PID/pagemap` 推断一切，却忽略权限、竞态和内核版本。

## 跨层连接

- OS 如何建立映射、处理 fault 和回收页面，见 [操作系统虚拟内存](../os/virtual-memory.md)；
- 进程的地址空间归属见 [进程与线程](../os/process-thread.md)；
- TLB shootdown 与多核通信进入 [缓存一致性](cache-coherence.md) 和 [CPU](cpu.md)；
- 文件映射页的驻留和回写进入 [文件系统](../os/filesystem.md)。

## Reference

- [Intel 64 and IA-32 Architectures Software Developer Manual, Volume 3](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html)
- [Arm Architecture Reference Manual for A-profile](https://developer.arm.com/documentation/ddi0487/latest/)
- [RISC-V Privileged Architecture Specification](https://docs.riscv.org/reference/isa/priv/priv-index.html)
- [Linux Kernel Documentation: Page Tables](https://www.kernel.org/doc/html/latest/mm/page_tables.html)
- [Linux Kernel Documentation: Transparent Hugepage Support](https://www.kernel.org/doc/html/latest/admin-guide/mm/transhuge.html)
- [Linux Kernel Documentation: Examining Process Page Tables](https://www.kernel.org/doc/html/latest/admin-guide/mm/pagemap.html)
