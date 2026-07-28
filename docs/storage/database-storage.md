# 数据库存储引擎

数据库把记录、索引和事务映射到页、日志和后台维护。设计的关键不是孤立选择 B+ tree 或 LSM，而是明确读放大、写放大、空间放大、恢复时间和并发控制怎样共同满足 workload。

<a id="pages"></a>
## 页、记录与缓冲池

数据库通常以固定大小 page 管理磁盘。slotted page 把 slot array 与变长 tuple data 从两端增长，移动记录时可保持稳定 slot。buffer pool 用 `(file, page_id)` 定位页，并维护：

- pin count：正在使用，不能驱逐；
- dirty bit 与 page LSN；
- replacement state；
- latch：保护内存结构，不等同事务 lock。

页大小增大会提高顺序带宽和树 fanout，却放大小随机读、写放大与缓存浪费。选择必须结合设备与记录分布。

<a id="btree"></a>
## B+ tree

内部节点只保存 separator key 与 child pointer，叶子保存记录或 record pointer，并常以链表连接支持范围扫描。若 fanout 为 $f$、记录数为 $N$：

$$
h\approx \lceil \log_f N\rceil
$$

高 fanout 让树高很小。插入可能 split 并向上传播；删除可能 merge/redistribute。并发实现要处理 latch coupling、页 split 可见性和恢复日志，不能只实现内存教科书树。

聚簇索引决定记录物理顺序，范围查询友好；多个二级索引会放大更新。二级索引指向主键时，主键变化和二次查找成本需要纳入模型。

<a id="lsm"></a>
## LSM tree

写先进入 WAL 与内存 memtable，冻结后顺序刷成 SSTable；后台 compaction 合并层级并丢弃旧版本/tombstone。Bloom filter 对不存在键减少无效读取：

$$
p_{\mathrm{fp}}\approx
\left(1-e^{-kn/m}\right)^k
$$

其中 $m$ 是 bit 数、$n$ 是键数、$k$ 是哈希数。最佳 $k\approx(m/n)\ln2$。

leveled compaction 限制同层重叠，读与空间放大较低、写放大较高；tiered/size-tiered 先累积多个 run，写更顺畅但查询需检查更多文件。tombstone 只有在不再遮蔽任何旧版本时才能安全清除。

<a id="wal-mvcc"></a>
## WAL、检查点与 MVCC

Write-Ahead Logging 的核心不变量：

$$
\mathrm{pageLSN}\le \mathrm{durableLSN}
\quad\text{before dirty page reaches disk}
$$

提交前 commit record 必须 durable；脏数据页可稍后写回。steal/no-force 缓冲策略提高性能，却要求恢复既能 REDO 已提交更新，也能 UNDO 未提交更新。checkpoint 缩短扫描范围，但不是“把所有页同步完”这一种实现。

MVCC 保存多个版本，让读者按 snapshot 选择可见记录。它减少读写阻塞，却引入版本回收、长事务阻止 vacuum、索引可见性与写写冲突。

<a id="cost-model"></a>
## 一个可用的成本模型

评估 workload 时至少估计：

$$
\begin{aligned}
\mathrm{read\ amplification}&=\frac{\text{physical bytes read}}{\text{logical bytes returned}}\\
\mathrm{write\ amplification}&=\frac{\text{physical bytes written}}{\text{logical bytes updated}}\\
\mathrm{space\ amplification}&=\frac{\text{physical live space}}{\text{logical live data}}
\end{aligned}
$$

命中 buffer pool 的查询主要消耗 CPU 与锁存器；miss 才暴露设备延迟。索引覆盖、压缩和 batch 会同时改变三类放大，不能只以单次点查 benchmark 排名。

## 失败模式与实践

- WAL 与数据在不同故障域时，任一丢失都可能无法恢复。
- `fsync` 延迟尖峰会形成 group commit 排队。
- LSM compaction 与用户 I/O 争抢带宽，触发 write stall。
- 长 snapshot 阻止版本与 tombstone 回收。
- 统计信息过时让优化器选择错误访问路径，这不是存储引擎吞吐问题。

实践中记录 WAL bytes、dirty pages、buffer hit、compaction debt、read/write/space amplification、checkpoint duration 与 recovery time。崩溃测试要在多个持久化边界注入，而不是只做正常关闭再启动。

## 向外连接

- [缓存、日志与崩溃一致性](caching-logging-consistency.md)继续追踪 WAL record、数据页与 flush 的崩溃顺序。
- [文件系统](filesystems.md)解释数据库最终依赖的 rename、`fsync` 与块分配边界。
- [事务与隔离](../distributed/transactions-isolation.md)把 MVCC 版本组织连接到 snapshot、serializability 与原子提交。
- [分片与再平衡](../distributed/sharding.md)展示单机索引和日志跨越复制组之后的新成本。

## Reference

- [ARIES: A Transaction Recovery Method](https://dl.acm.org/doi/10.1145/128765.128770)
- [The Ubiquitous B-Tree](https://dl.acm.org/doi/10.1145/356770.356776)
- [The Log-Structured Merge-Tree](https://www.cs.umb.edu/~poneil/lsmtree.pdf)
- [The Case for Learned Index Structures](https://research.google/pubs/the-case-for-learned-index-structures/)
- [PostgreSQL Database Page Layout](https://www.postgresql.org/docs/current/storage-page-layout.html)
- [PostgreSQL Write-Ahead Logging](https://www.postgresql.org/docs/current/wal-intro.html)
- [PostgreSQL MVCC](https://www.postgresql.org/docs/current/mvcc-intro.html)
- [SQLite Database File Format](https://www.sqlite.org/fileformat.html)
