# 缓存、日志与崩溃一致性

崩溃一致性研究的不是正常执行结果，而是电源在任意持久化边界消失后，系统能否恢复到一个满足不变量的状态。CPU 内存屏障、编译器顺序、块设备 flush、文件系统 journal 与数据库 WAL 是不同层次的顺序机制，不能互相替代。

<a id="failure-model"></a>
## 先写故障模型

需要明确：

- 进程崩溃还是整机掉电；
- DRAM、设备 cache、NVDIMM 哪些仍保留；
- 扇区/atomic write unit 是否会 torn；
- 写入是否可能重排；
- 介质会否静默损坏；
- 故障是否独立，控制器和多个盘是否共享电源。

没有故障模型，“写入是原子的”没有可检验含义。

<a id="wal"></a>
## WAL 协议

设数据页更新日志 LSN 为 $l$。安全写回要求：

$$
\mathrm{durableLSN}\ge l
$$

提交返回前，事务的 commit record 也必须 durable。group commit 把多个事务的日志放进同一次 flush，摊薄固定成本：

$$
\mathrm{cost/txn}\approx
\frac{T_{\mathrm{flush}}+T_{\mathrm{batch}}}{B}
$$

batch 大小 $B$ 提升吞吐，却增加等待窗口。正确实现还要处理短写、`EINTR`、磁盘满、I/O error 与日志 checksum，不能把 `fsync` 失败记日志后继续宣告成功。

<a id="cow-shadow"></a>
## CoW、Shadow Paging 与双写

CoW/Shadow Paging 先写新页，再原子切换根；旧根仍指向一致快照。它减少 UNDO，却需要管理可达性、回收与根更新原子性。双写缓冲先保存整页副本，再写 home page，用于恢复 torn page；它与 WAL 解决的问题不同。

| 机制 | 主要保护 | 仍需处理 |
| --- | --- | --- |
| WAL | 操作顺序、REDO/UNDO | torn page、日志损坏 |
| CoW | 旧/新树切换 | 空间回收、碎片 |
| checksum | 检测静默损坏 | 从冗余恢复 |
| replication | 节点/介质故障 | 共同软件错误、一致损坏 |

<a id="cache-coherence"></a>
## 多层缓存的持久边界

`write` 到 page cache 后，文件可能对其他进程可见但仍不耐掉电。`fsync(file)` 推进文件数据和必要元数据；新增名字或 rename 后还需考虑 `fsync(directory)`。块层将 flush/FUA 传给设备，设备必须诚实实现缓存语义。

远端存储又增加网络确认与副本 quorum：客户端收到 ACK 之前，必须知道确认的是远端内存、远端持久日志还是多个故障域的 durable copy。接口文档应直接声明，而非只写“写成功”。

<a id="recovery"></a>
## 恢复是一段可重放程序

恢复必须幂等：恢复过程中再次崩溃，下一次仍能继续。典型阶段：

1. 定位最后完整 checkpoint；
2. 扫描日志并验证长度、LSN、checksum；
3. REDO 可能已提交但未落页的更新；
4. UNDO loser transactions，写 compensation log record；
5. 重建派生结构或标记后台修复；
6. 在开放服务前验证全局不变量。

日志解析必须把截断尾部视为预期崩溃状态，把中间 checksum 错误视为损坏；两者处理不同。

<a id="test"></a>
## 崩溃测试与测量

一个可重复的测试矩阵：

```text
for each persistence boundary:
  prepare known state
  start one logical update
  crash before/after boundary
  restart and recover
  assert state is exactly old or new
  assert indexes, free lists and checksums agree
  repeat crash during recovery
```

使用进程 kill 只能覆盖进程崩溃，不能模拟设备缓存掉电。真实 power-cut 测试必须用隔离硬件与可恢复数据。dm-flakey、fault injection 与确定性模拟适合扩大状态空间，但结果只能对应其建模的故障。

性能报告同时给出 commit latency 分布、group size、WAL bytes、flush latency、checkpoint interference 与恢复时长。关闭同步得到的峰值吞吐不能与 durable commit 比较。

## 穿过持久边界

- [文件系统](filesystems.md)具体说明 journal、CoW、rename 与目录持久化。
- [数据库存储引擎](database-storage.md)把 WAL、page LSN、checkpoint 和 MVCC 放进同一引擎。
- [存储层次与块 I/O](hierarchy-devices.md)沿 page cache、blk-mq 与设备 cache 追踪 ACK。
- [分布式存储](../distributed/distributed-storage.md)进一步区分本地 durable、quorum durable 与跨故障域恢复。

## Reference

- [ARIES: A Transaction Recovery Method](https://dl.acm.org/doi/10.1145/128765.128770)
- [SQLite Atomic Commit](https://www.sqlite.org/atomiccommit.html)
- [SQLite WAL](https://www.sqlite.org/wal.html)
- [ext4 Journal](https://www.kernel.org/doc/html/latest/filesystems/ext4/journal.html)
- [fsync(2) — Linux manual page](https://man7.org/linux/man-pages/man2/fsync.2.html)
- [Linux device-mapper delay and flakey targets](https://docs.kernel.org/admin-guide/device-mapper/delay.html)
- [Pillai et al.: All File Systems Are Not Created Equal](https://www.usenix.org/conference/osdi14/technical-sessions/presentation/pillai)
