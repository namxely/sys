# 操作系统虚拟内存

硬件 [MMU 与 TLB](../architecture/virtual-memory-tlb.md) 提供翻译和保护机制；操作系统决定哪些虚拟区间存在、映射到什么、何时分配物理页、如何共享与回收。虚拟内存既是隔离边界，也是统一匿名内存、文件和设备映射的命名空间。

## VMA 与 PTE 是不同层

Linux 用 VMA 描述一段具有共同属性的虚拟地址区间，例如：

- 匿名 heap/stack；
- 可执行文件代码和只读数据；
- `mmap` 文件；
- shared memory；
- 设备映射。

VMA 说明“这段地址应当怎样”，PTE 说明“某一页当前怎样映射”。VMA 存在不代表每页已有物理页或 PTE；按需分页会在首次访问时补全。

## page fault 状态机

CPU 访问虚拟地址：

```text
TLB hit -> permission check -> cache/memory
TLB miss -> page-table walk
    PTE valid -> refill TLB
    PTE absent/protection fault -> enter kernel
        no matching VMA / illegal permission -> signal
        anonymous first touch -> allocate zeroed page
        file page cached -> install PTE
        file page absent -> start I/O, sleep, retry
        copy-on-write -> allocate/copy/remap
```

fault 是正常控制流的一部分，但 fault 路径需要内核分配、加锁、可能 I/O 和 TLB 失效，尾延迟远高于普通访问。

## 匿名页、文件页与 page cache

匿名页没有普通文件后备，压力下可留在内存、压缩或写入 swap。文件映射页由文件偏移作为后备，可与 `read/write` 的 page cache 共享物理缓存。

`mmap` 不等于“文件已经读入内存”，也不必比 `read` 更快。它把 I/O 时机转为 page fault，并减少显式复制/系统调用；随机访问、错误处理、truncate 竞态和地址空间压力也随之进入应用路径。

## copy-on-write

`fork` 和私有文件映射可共享只读物理页。写入时：

1. CPU 因 PTE 不可写触发 fault；
2. 内核确认这是合法 COW；
3. 分配并复制页；
4. 更新写方映射和引用计数；
5. 完成 TLB 同步后重试。

COW 节省未被修改页的复制，却可能把大量复制延迟推迟到请求关键路径。多线程大进程 `fork` 后若子进程长期运行，父进程写热点会产生显著 fault 与 RSS 增长。

## 分配不等于驻留

`malloc` 通常只管理虚拟区间和用户态 allocator 元数据；物理页常在首次写触发 fault 时分配。Linux overcommit 还允许承诺的虚拟内存超过可立即提供的物理/交换空间。

因此：

- VIRT 大不等于 RSS 大；
- RSS 大不等于工作集都热；
- allocator 已返回不等于后续触页不会失败或抖动；
- `free` 不保证 RSS 立即下降，allocator 可能保留 arena。

## 页面回收

内存压力下，内核在可回收页中选择：

- 干净文件页可直接丢弃；
- 脏文件页需要 writeback；
- 匿名页可能写 swap；
- pinned、mlock 或不可回收页不能直接释放。

访问位、代际/LRU 近似和 refault 信息用于估计工作集。回收过猛会造成 thrashing：任务刚读回的页很快又被驱逐，CPU 与存储都很忙却几乎不推进有效工作。

PSI memory 的 `some` 表示至少一些任务因内存压力停顿，`full` 表示所有非 idle 任务同时停顿。它比单看 free memory 更接近用户可感知压力。

## huge page

huge page 扩大 TLB reach、减少页表和部分 fault 数量。代价包括内部碎片、连续内存分配、collapse/拆分页延迟和细粒度回收困难。

Linux 提供显式 HugeTLB 与 Transparent Huge Pages。THP 策略、支持页大小和默认值依内核/发行版而变，应用应记录实际 `/sys/kernel/mm/transparent_hugepage/` 状态。

## `mmap` 的可验证示例

下面的 POSIX C11 程序创建文件、调整长度、映射、写入并用 `msync` 请求同步：

```c
#define _POSIX_C_SOURCE 200809L
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
int main(void) {
    const size_t n = 4096;
    int fd = open("mapped.bin", O_RDWR | O_CREAT | O_TRUNC, 0644);
    if (fd < 0 || ftruncate(fd, (off_t)n) < 0) { perror("open/ftruncate"); return 1; }
    char *p = mmap(NULL, n, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (p == MAP_FAILED) { perror("mmap"); return 1; }
    memcpy(p, "state=ready\n", 12);
    if (msync(p, n, MS_SYNC) < 0) { perror("msync"); return 1; }
    if (munmap(p, n) < 0 || close(fd) < 0) return 1;
}
```

`msync` 的数据与元数据持久化边界依操作系统和文件系统语义；若还要求目录项在崩溃后存在，需要按[文件系统](filesystem.md)中的协议处理文件和父目录 `fsync`。内存映射期间并发 truncate 也可能导致访问信号。

## NUMA 放置

Linux NUMA policy 可按进程/线程和地址范围选择 default、bind、preferred、interleave 等策略。页通常在 fault 时实际放置，因此初始化在哪个 CPU 发生很重要。

诊断：

```bash
numactl --hardware
numastat -p $PID
grep -E 'VmRSS|VmSwap|RssAnon|RssFile' /proc/$PID/status
cat /proc/$PID/numa_maps
```

这些是快照。结合线程迁移 trace 和内存控制器数据判断“远端页”是否真的在关键路径。

## 怎样测量

- `getrusage` 或 `perf stat`：minor/major fault；
- `/proc/PID/smaps_rollup`：RSS/PSS/匿名/文件映射；
- `/proc/vmstat`：系统回收、swap、fault 计数；
- PSI：任务因内存压力停顿的时间；
- tracepoint：fault、reclaim、compaction、writeback 时间线；
- DAMON：采样数据访问模式，需明确开销与配置。

先区分分配量、驻留量、活跃工作集和可回收量，再解释 OOM 或延迟。

## OOM 不是简单的“free=0”

分配失败还取决于：

- NUMA/node 与 zone 限制；
- order 和连续性；
- cgroup `memory.max`；
- 可回收页、脏页和 pinned 页；
- overcommit 策略；
- 内核保留与水位。

cgroup OOM 与全局 OOM 的作用域不同。OOM killer 选择牺牲任务是恢复策略，不保证业务一致性，应用仍要设计重启和持久化。

## 失败模式

- 把 VIRT、RSS、PSS 和 working set 混为一谈；
- `mmap` 后认为 I/O 已完成；
- 在请求路径首次触碰巨大映射，产生 fault 峰值；
- 开启 THP 却不测 compaction 与尾延迟；
- 只限制容器 RSS，不观察 page cache、swap 和 PSI；
- 多线程大进程 `fork` 后长期写入；
- 看到 major fault 就直接归因磁盘，忽略远端/网络文件系统和统计边界；
- 依赖 `/proc` 某字段而不记录内核版本。

## 跨层连接

- 页表、TLB 与 shootdown 的硬件机制见[虚拟内存与 TLB](../architecture/virtual-memory-tlb.md)；
- 地址空间归属与 COW 起点见[进程与线程](process-thread.md)；
- file-backed page 与回写见[文件系统](filesystem.md)；
- memory cgroup 与 OOM 作用域见[隔离与容器](isolation-containers.md)。

## Reference

- [Linux Kernel Documentation: Memory Management](https://www.kernel.org/doc/html/latest/mm/index.html)
- [Linux Kernel Documentation: Process Addresses](https://www.kernel.org/doc/html/latest/mm/process_addrs.html)
- [Linux Kernel Documentation: Page Tables](https://www.kernel.org/doc/html/latest/mm/page_tables.html)
- [Linux Kernel Documentation: Multi-Gen LRU](https://www.kernel.org/doc/html/latest/admin-guide/mm/multigen_lru.html)
- [Linux Kernel Documentation: NUMA Memory Policy](https://www.kernel.org/doc/html/latest/admin-guide/mm/numa_memory_policy.html)
- [Linux mmap(2)](https://www.man7.org/linux/man-pages/man2/mmap.2.html)
- [Linux proc_pid_smaps(5)](https://www.man7.org/linux/man-pages/man5/proc_pid_smaps.5.html)
- [Linux PSI](https://www.kernel.org/doc/html/latest/accounting/psi.html)
