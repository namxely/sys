# 拓扑与通信优化

并行程序看到的是 threads、ranks、devices，硬件提供的是 sockets、NUMA nodes、cache domains、PCIe switches、GPU links、NICs 和 network fabric。错误放置会让同一算法的通信跨越更慢、更拥塞的层级。

<a id="hierarchy"></a>
## 通信层次

典型延迟/带宽层次：

```text
thread-local registers (not a cross-thread communication channel)
  -> same core / same shared-cache domain via shared memory
  -> same NUMA node memory
  -> cross-socket interconnect
  -> GPU HBM / peer link
  -> PCIe host/device
  -> same-node NIC
  -> same-rack / cross-rack network
```

寄存器属于执行线程的私有状态，普通线程或 rank 不能直接读取彼此寄存器；同核线程的通信仍需通过架构定义的共享内存与同步。其余层次的具体顺序和共享关系依机器而变，必须从拓扑查询和 microbenchmark 得到。逻辑 device ID 不保证物理相邻。

<a id="mapping"></a>
## 放置与数据分区

目标是让主要通信边留在便宜层级。若一个 node 有 $g$ 张 GPU、每 GPU 若干 rank：

- tensor/domain decomposition 的高频邻居映射到 NVLink/同 switch；
- 跨节点通信聚合后由本地 NIC 发出；
- CPU communication thread 绑定到 NIC/GPU 相近 NUMA node；
- memory first-touch 与使用线程一致；
- 多 rail 映射避免所有 rank 压到同一 HCA。

拓扑映射本质是图映射：最小化

$$
\sum_{(i,j)\in E_{\text{comm}}}
w_{ij}\,c\bigl(\phi(i),\phi(j)\bigr)
$$

$w_{ij}$ 是逻辑通信量，$c$ 是物理位置通信成本。

<a id="communication-avoiding"></a>
## 减少 bytes、messages 与同步

优化顺序：

1. **避免通信**：改变算法/分解，增加本地复用；
2. **聚合消息**：用一个大消息摊薄 $\alpha$；
3. **重叠**：在不破坏依赖下同时计算与传输；
4. **拓扑感知 collective**：先节点内归约，再跨节点；
5. **压缩**：仅在压缩开销与误差值得时。

double buffering 可以形成流水线：

```text
iteration k: compute(buffer A) || transfer(buffer B)
swap only after both dependencies complete
```

必须用 event/request 表达真正依赖，不能用固定 sleep 或假定 kernel launch 已完成。

<a id="contention"></a>
## 竞争与热点

单链路 microbenchmark 的峰值不代表 all-to-all。共享 PCIe root、NIC、spine 链路和 switch queue 都可能 oversubscribe。collective 中一个慢 rank 会成为全局关键路径；不均可能源于 CPU 调度、GPU 降频、page fault 或网络热点。

通信时间可扩展为：

$$
T=\alpha m+\beta n+\gamma f+T_{\text{contention}}+T_{\text{sync}}
$$

$m$ 是消息数、$n$ 是字节数、$f$ 是归约操作量。最后两项通常不能从单进程 benchmark 推出。

<a id="tools"></a>
## 发现与测量

```text
lscpu -e=CPU,NODE,SOCKET,CORE,CACHE
numactl --hardware
nvidia-smi topo -m
ibdev2netdev
```

结合 `hwloc`、MPI rank binding 输出、Nsight Systems 和交换机/NIC counters。报告 topology diagram、rank map、message matrix、P50/P99 collective latency 与每链路吞吐。

故障实验包括禁用一条 rail、降低一个 GPU clocks、注入一个 rank 延迟、改变 ECMP seed。优化必须在多种消息尺寸和规模上验证，避免只对一个拓扑点过拟合。

## 邻接层

- [MPI 与集合通信](mpi-collectives.md)把 rank map 转化为 point-to-point 与 collective 流量。
- [CUDA 编程模型](cuda.md)说明 stream、kernel 与多 GPU 依赖如何产生通信。
- [共享内存与 OpenMP](shared-memory-openmp.md)连接 CPU affinity、first touch 和 NUMA locality。
- [数据中心网络与 RDMA](../network/datacenter-rdma.md)继续追踪 HCA、ECMP、PFC 与跨机架 fabric。

## Reference

- [hwloc documentation](https://www.open-mpi.org/projects/hwloc/doc/)
- [Linux NUMA memory policy](https://docs.kernel.org/admin-guide/mm/numa_memory_policy.html)
- [CUDA Programming Guide: Multi-GPU Systems](https://docs.nvidia.com/cuda/cuda-programming-guide/index.html)
- [NVIDIA GPUDirect RDMA](https://docs.nvidia.com/cuda/gpudirect-rdma/)
- [MPI 5.0 Process Topologies](https://www.mpi-forum.org/docs/mpi-5.0/mpi50-report/mpi50-report.htm)
- [Hoefler and Snir: Generic Topology Mapping Strategies](https://www.alcf.anl.gov/publications/generic-topology-mapping-strategies-large-scale-parallel-architectures)
