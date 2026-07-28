# 存储系统

存储的核心不是“把字节写进磁盘”，而是在性能、持久性、容量与故障恢复之间定义清楚的契约。应用调用 `write()`、内核页缓存变脏、设备确认命令、介质真正保留数据，是四个不同事件；系统设计必须明确哪一个事件才允许向用户宣告成功。

## 学习路径

1. [存储层次与块 I/O](hierarchy-devices.md)：从访问局部性、队列和页缓存建立成本模型。
2. [SSD 与 NVMe](ssd-nvme.md)：理解 flash 的擦写约束、FTL、写放大和多队列接口。
3. [文件系统](filesystems.md)：从 inode、目录、extent 到 journaling、CoW 与崩溃恢复。
4. [数据库存储引擎](database-storage.md)：比较页式组织、B+ tree、LSM、MVCC 与 WAL。
5. [缓存、日志与崩溃一致性](caching-logging-consistency.md)：把易失缓存、顺序点和恢复不变量串成协议。

## 三个必须分开的性质

| 性质 | 问题 | 典型机制 |
| --- | --- | --- |
| 原子性 | 崩溃后看到旧值还是新值，能否看到撕裂中间态 | WAL、CoW、atomic write |
| 持久性 | 返回成功的数据是否跨电源故障保留 | flush/FUA、`fsync`、可靠介质 |
| 顺序性 | 数据、元数据和提交记录以什么顺序可持久观察 | barrier、flush、日志协议 |

复制不是本地持久性的替代：多个副本可能同时确认仍在易失缓存中的同一错误状态。校验和也不等于冗余：它能检测损坏，却不能凭空恢复正确数据。

## 性能坐标

一次存储操作至少报告：

- 请求大小、随机/顺序、读写比例与地址分布；
- 队列深度、并发线程、同步/异步；
- buffered/direct I/O、预热与工作集；
- 吞吐、IOPS、P50/P99/P99.9 和错误；
- 持久性语义：是否 `fsync`、FUA、掉电保护；
- 设备、文件系统、挂载选项、内核与基准时长。

$$
\mathrm{throughput}=\mathrm{IOPS}\times \mathrm{average\ request\ size}
$$

公式只是单位关系，不表示增加请求大小总能线性提速；设备并行度、控制器、总线与写放大都会成为瓶颈。

## Reference

- [Linux block layer documentation](https://docs.kernel.org/block/index.html)
- [NVM Express specifications](https://nvmexpress.org/specifications/)
- [Linux filesystems documentation](https://docs.kernel.org/filesystems/index.html)
- [SQLite Atomic Commit](https://www.sqlite.org/atomiccommit.html)
