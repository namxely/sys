# 存储层次与块 I/O

<a id="hierarchy"></a>
## 为什么需要层次

速度快、容量大、价格低、掉电不失四个目标很难同时满足。系统因此把寄存器、缓存、DRAM、持久内存、SSD、HDD 和远端存储组织成层次，并用时间与空间局部性把热点留在上层。

平均访问时间可粗略写为：

$$
T_{\text{avg}}=hT_{\text{hit}}+(1-h)(T_{\text{miss}}+T_{\text{fill}})
$$

命中率 $h$ 很高仍不代表尾延迟安全：miss 可能触发磁盘排队、远端恢复或级联驱逐。层次中的每一层还带来一致性问题——同一逻辑块可能同时存在于 CPU cache、page cache、设备 DRAM 和介质。

<a id="block-path"></a>
## Linux 块 I/O 路径

buffered write 的典型路径：

```text
application
  -> VFS / filesystem
  -> page cache becomes dirty
  -> writeback builds bio
  -> blk-mq queues request
  -> driver / controller
  -> device volatile cache
  -> persistent media
```

`write()` 返回通常只说明数据复制进内核缓存。`fsync()` 请求把文件数据和恢复该文件所需元数据推进到持久边界；目录项创建、重命名等还可能要求同步目录。Direct I/O 绕过 page cache 的数据缓存路径，但并不自动保证介质持久，也不取消文件系统元数据工作。

blk-mq 为 CPU 与硬件队列提供多队列映射，减少单锁争用并利用设备内部并行。scheduler 的目标可能是合并、延迟公平或优先级；高速 NVMe 上调度收益和 CPU 开销需实测。

<a id="queueing"></a>
## 并发、队列深度与尾延迟

Little 定律：

$$
Q=\lambda W
$$

若设备在 100 µs 平均时延下完成 200k IOPS，平均在途请求约 20。提高 queue depth 能暴露并行度，但超过饱和点后吞吐趋平、排队时延继续增长。

HDD 的随机访问包含 seek 与旋转，顺序合并极其重要；SSD 没有机械寻道，却受 channel/die 并行、垃圾回收和 FTL 映射影响。把两者都简化为“固定延迟块设备”会掩盖关键尾部行为。

<a id="cache"></a>
## Page cache 与一致性

page cache 统一文件读写缓存；readahead 利用顺序性，writeback 批量下刷脏页。`mmap` 与 `read/write` 可命中同一页缓存，但应用必须遵守同步与文件截断语义。

缓存压力下的风险：

- 脏页积累后集中 writeback，造成长时间抖动；
- readahead 污染缓存，驱逐真正热点；
- 多个 cgroup/租户争用同一设备队列；
- benchmark 只测 DRAM cache，误称设备吞吐；
- 设备写缓存无掉电保护，却把 flush 配置错误。

## 测量方法

```text
lsblk -o NAME,TYPE,SIZE,ROTA,DISC-MAX,PHY-SEC,LOG-SEC
cat /sys/block/nvme0n1/queue/scheduler
iostat -x 1
cat /proc/meminfo
```

用 `fio` 时明确 `direct`、`ioengine`、`iodepth`、`numjobs`、`bs`、`rw`、`fsync` 与数据校验。先记录设备稳态和温度；短暂 SLC cache 峰值不能代表持续写性能。

## 顺着 I/O 路径继续

- [SSD 与 NVMe](ssd-nvme.md)展开控制器队列、FTL、Flash 并行与持久化命令。
- [文件系统](filesystems.md)说明块设备之上如何组织名字、extent、日志与恢复。
- [缓存、日志与崩溃一致性](caching-logging-consistency.md)把 page cache、设备 cache 与 WAL 的持久边界串起来。

## Reference

- [Linux block layer documentation](https://docs.kernel.org/block/index.html)
- [Multi-Queue Block IO Queueing Mechanism](https://docs.kernel.org/block/blk-mq.html)
- [Linux page cache documentation](https://docs.kernel.org/mm/page_cache.html)
- [fsync(2) — Linux manual page](https://man7.org/linux/man-pages/man2/fsync.2.html)
- [open(2) — Linux manual page](https://man7.org/linux/man-pages/man2/open.2.html)
- [fio documentation](https://fio.readthedocs.io/en/latest/fio_doc.html)
