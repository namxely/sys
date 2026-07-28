# 文件系统

文件系统把块地址空间变成文件、目录、权限和命名操作，同时在崩溃后恢复结构不变量。它不是数据库事务：`rename` 的原子命名语义、`fsync` 的持久语义和多文件更新的原子性必须分别理解。

<a id="layout"></a>
## 对象与磁盘布局

典型 Unix 文件系统包含：

- superblock：全局几何、特性与状态；
- inode：类型、权限、大小、时间、数据块映射；
- directory：名字到 inode 的映射；
- allocation metadata：哪些 inode/blocks 已使用；
- data blocks/extents：文件内容；
- journal 或 CoW 元数据：恢复所需状态。

硬链接是多个目录项指向同一 inode；符号链接存路径字符串。删除目录项只减少 link count，仍被打开的 inode 可继续存在，直到引用和链接都归零。

extent 用 `(logical start, physical start, length)` 描述连续范围，比逐块指针更适合大文件。稀疏文件的逻辑范围可以没有物理块；读取 hole 返回零。

<a id="allocation"></a>
## 分配、局部性与碎片

分配器希望相关 inode、目录和数据靠近，以减少 HDD seek 并改善 readahead；SSD 上连续大 I/O 仍能减少命令与映射开销。delayed allocation 在更多写入信息到达后再选择 extent，可改善布局，却扩大“写已返回、块尚未分配”的窗口。

碎片有两类：

- 空间碎片：extent 不连续，元数据和 I/O 数增加；
- 时间碎片：冷热数据混放，使 SSD GC 或 CoW 清理放大。

<a id="journaling"></a>
## Journaling

以 metadata journaling 为例，一次更新通常：

1. 把将要修改的元数据写入 journal；
2. 先让本事务的 journal data/descriptor durable；
3. 再写 commit record，并用 FUA、barrier 或后续 flush 让它自身 durable；
4. 只有在 commit record 的持久完成可确认后，事务才可作为已提交对外生效；
5. 后台 checkpoint 到 home location，确认安全后回收 journal 空间。

崩溃恢复只重放有完整且可验证 commit 的事务。write-ahead 不变量不只有“日志先于 home block”，还包括“commit record 不得越过它所确认的 journal data”；易失设备缓存存在时，普通写入完成不足以证明这两个边界。ext4 默认 `data=ordered` 只 journal 元数据，但在提交相关元数据前排序对应数据写；`data=journal` 才对数据和元数据都日志化。

<a id="cow"></a>
## Copy-on-Write 与日志结构

CoW 不覆盖旧块，而是写新数据/元数据，最后原子切换根指针。快照和校验和自然，但随机覆盖会导致碎片、引用计数与清理成本。日志结构文件系统把新数据顺序追加到 segment，再由 cleaner 回收低利用率 segment：

$$
\text{cleaning cost}\propto
\frac{\text{read live}+\text{write live}}{\text{free reclaimed}}
$$

空间接近满载时，找到低活跃 segment 变难，清理放大显著。

<a id="posix-durability"></a>
## 应用可依赖什么

安全替换单文件的典型模式：

```text
write temp in same directory
fsync(temp)
rename(temp, target)
fsync(parent directory)
```

它仍应检查每一步返回值，并处理文件权限、扩展属性与空间耗尽。`rename` 保证命名切换原子，不自动保证重启后目录项已持久。跨文件系统 rename 不具备同一原子语义。

不要依据某个文件系统一次实验推断 POSIX 的全部持久保证；内核版本、挂载模式、设备 flush 和错误处理都会改变边界。

## 测量与恢复

- 分开测 create/stat、顺序读写、随机更新、`fsync` 和 directory-heavy workloads。
- 制造磁盘满、inode 满、只读 remount、I/O error 与崩溃点。
- 恢复验证检查的不只是“能 mount”，还包括应用不变量和校验和。
- 观察 dirty pages、journal commit latency、extent/fragmentation 和 block latency。

## 与上下层对齐

- [存储层次与块 I/O](hierarchy-devices.md) 给出 page cache、writeback 和设备队列的下层路径。
- [缓存、日志与崩溃一致性](caching-logging-consistency.md)比较 WAL、CoW、双写与恢复协议。
- [数据库存储引擎](database-storage.md)说明数据库页、WAL 与文件系统持久语义如何叠加。

## Reference

- [ext4 High Level Design](https://www.kernel.org/doc/html/latest/filesystems/ext4/overview.html)
- [ext4 Journal (jbd2)](https://www.kernel.org/doc/html/latest/filesystems/ext4/journal.html)
- [The Design and Implementation of a Log-Structured File System](https://people.eecs.berkeley.edu/~brewer/cs262/LFS.pdf)
- [Btrfs documentation](https://btrfs.readthedocs.io/en/latest/)
- [XFS documentation](https://docs.kernel.org/filesystems/xfs/index.html)
- [rename(2) — Linux manual page](https://man7.org/linux/man-pages/man2/rename.2.html)
- [fsync(2) — Linux manual page](https://man7.org/linux/man-pages/man2/fsync.2.html)
