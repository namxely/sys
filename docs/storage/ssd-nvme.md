# SSD 与 NVMe

<a id="flash"></a>
## NAND Flash 的不对称约束

NAND 以 page 读取和编程、以更大的 erase block 擦除；不能像 DRAM 一样原地覆盖任意字节。更新逻辑页时，SSD 通常把新内容写到空闲物理页，更新映射，旧页标记无效，随后垃圾回收搬运有效页并擦除整块。

因此主机写入量与 NAND 实际写入量不同：

$$
\mathrm{WAF}=
\frac{\text{bytes programmed to NAND}}
{\text{bytes written by host}}
$$

在不考虑设备内压缩、去重等数据缩减时，常见口径下 $\mathrm{WAF}\ge 1$；若设备改变了实际写入的数据量，必须把这些机制写进测量口径，不能把下界当作无条件数学性质。随机小写、低空闲空间、混合冷热数据会提高写放大。TRIM/Discard 告诉设备哪些逻辑块不再有效，帮助回收，但在线 discard 的延迟影响需要按负载测量。

<a id="ftl"></a>
## FTL、并行与尾延迟

Flash Translation Layer 维护 LBA 到物理页映射，并承担：

- 地址映射与重定向写；
- 垃圾回收；
- wear leveling；
- bad block 管理和 ECC；
- 掉电恢复元数据。

控制器把请求分布到 channel、package、die 和 plane。多个独立请求可并行；单个巨大顺序请求未必获得最佳尾延迟。后台 GC、热节流、读扰动和映射缓存 miss 会制造长尾。

设备宣称的 endurance 常以 TBW/DWPD 表达，但应用层 WAF、文件系统 CoW、数据库 compaction 与设备 WAF 会相乘。只看 host bytes written 无法估计 NAND 磨损。

<a id="nvme"></a>
## NVMe 的多队列接口

NVMe 面向 PCIe 非易失存储设计。主机在内存中维护 submission queue 和 completion queue，doorbell 通知控制器。一个 admin queue 管理设备，多个 I/O queue pair 可按 CPU 分配，降低共享锁与中断争用。

一次命令路径：

1. 主机填写 SQ entry，确保描述符和数据映射可见；
2. 更新 SQ tail doorbell；
3. 控制器 DMA 读取命令与数据；
4. 执行后写入 CQ entry；
5. 中断或 polling 通知主机，主机推进 CQ head。

队列深度增加能暴露 flash 并行，却会增加排队。低延迟目标应在吞吐拐点前选择 QD，不是把 QD 固定到最大。

<a id="persistence"></a>
## 完成、Flush 与掉电保护

命令 completion 语义取决于设备缓存与命令标志。易失写缓存启用时，普通写完成不必等于 NAND 已持久；Flush 命令、FUA 和具备 power-loss protection 的设备构成不同持久路径。

必须从应用一直审计到硬件：

```text
transaction commit
 -> database WAL sync
 -> filesystem fsync
 -> block flush/FUA
 -> controller cache policy
 -> persistent media or protected cache
```

任何一层忽略 flush 或错误宣告安全，都会破坏上层持久性证明。

<a id="zns"></a>
## Zoned Namespace

ZNS 把地址空间划为 zone，要求按写指针顺序写入并显式 reset。它把部分数据放置与 GC 决策交给主机，可能降低设备内部写放大，但上层必须管理 zone 状态、回收和故障恢复；它不是对任意文件系统透明的“更快模式”。

## 测量与故障

- 在预处理后的稳态测 sustained read/write，而非只测出厂空盘。
- 区分 QD、线程数、block size、读写比和随机分布。
- 监控温度、media errors、available spare、percentage used 与 unsafe shutdowns。
- 用校验数据检测静默损坏；断电测试需隔离设备并验证恢复，不用生产数据试验。
- 观察 P99.9 随写入时间的曲线，识别 SLC cache 耗尽和 GC 周期。

## 放回完整存储栈

- [存储层次与块 I/O](hierarchy-devices.md)解释 NVMe queue 如何接到文件系统、page cache 与 blk-mq。
- [缓存、日志与崩溃一致性](caching-logging-consistency.md)追踪 Flush、FUA 和 commit ACK 的持久边界。
- [数据库存储引擎](database-storage.md)展示 compaction、WAL 与设备 WAF 怎样叠加。

## Reference

- [NVM Express Base Specification](https://nvmexpress.org/specification/nvm-express-base-specification/)
- [NVM Express NVM Command Set Specification](https://nvmexpress.org/specifications/)
- [Linux NVMe documentation](https://docs.kernel.org/nvme/index.html)
- [Linux Zoned Storage documentation](https://docs.kernel.org/next/filesystems/zonefs.html)
- [FAST '12: The Bleak Future of NAND Flash Memory](https://www.usenix.org/conference/fast12/bleak-future-nand-flash-memory)
- [FAST '16: The Tail at Store](https://www.usenix.org/conference/fast16/technical-sessions/presentation/hao)
