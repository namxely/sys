# 隔离与容器

容器不是单个内核功能，也不是轻量虚拟机的同义词。Linux 容器把 namespace 的“看见什么”、cgroup 的“能用多少”、capability/seccomp/LSM 的“允许做什么”与 root filesystem、镜像和运行时生命周期组合起来。

## namespace：改变资源视图

Linux 提供多类 namespace：

| namespace | 隔离的视图 |
| --- | --- |
| mount | mount tree、传播关系 |
| PID | 进程 ID 与层级 |
| network | 网卡、路由、端口、netfilter |
| IPC | SysV IPC、POSIX message queue |
| UTS | hostname、domain name |
| user | UID/GID 与 capability 映射 |
| cgroup | cgroup 路径视图 |
| time | 部分系统时钟偏移 |

namespace 主要隔离名字和可见性，不直接限制 CPU、内存或 I/O 消耗。PID namespace 中的 PID 1 还承担信号与孤儿回收语义，普通应用作为容器 init 时必须正确 wait 子进程。

## cgroup v2：资源域

cgroup v2 以单一层级组织进程，并由 controller 管理：

- `cpu.max`：CPU bandwidth；
- `cpu.weight`：竞争时的相对权重；
- `memory.max/high/low/min`：硬上限、回收节流与保护；
- `io.max/weight`：块 I/O 限制/权重；
- `pids.max`：进程数量；
- cpuset：允许 CPU 和 NUMA 节点。

limit 不等于预留，weight 不等于固定比例。CPU quota 可能产生周期性 throttling；`memory.high` 主要施加回收压力，`memory.max` 才是硬边界，具体事件可从 `memory.events` 观察。

### delegation 不只是 chmod

安全 delegation 需要控制哪些 cgroup 文件可写，并满足 no-internal-process 等规则。若把整个宿主 cgroupfs 暴露给容器，即使 namespace 隐藏部分路径，也可能泄漏或越权。

## capability：拆分 root 权限

Linux capability 把传统 root 权限拆成多个集合和位。进程有 permitted、effective、inheritable、bounding、ambient 等集合；user namespace 还改变 capability 相对哪个 user namespace 生效。

最小权限原则不是“把所有 capability drop 掉就完成”：

- 需要同时收紧文件权限、设备、mount 和 syscall；
- capability 过宽，如 `CAP_SYS_ADMIN`，覆盖大量敏感操作；
- setuid/file capability 与 exec 会改变集合；
- 宿主内核仍是共享信任边界。

## seccomp 与 LSM

seccomp-BPF 按系统调用号和参数过滤 syscall，可返回 allow、errno、kill、trap、notify 等动作。它不是完整 sandbox：

- 允许的 syscall 仍可能操作已持有的强大 fd；
- syscall 号和参数 ABI 依架构；
- race 与间接资源权限不由过滤器自动解决。

SELinux、AppArmor、Landlock 等 LSM 可按安全策略约束对象访问；它们与 namespace、capability、seccomp 互补。

## root filesystem 与 mount

chroot 只改变 pathname 解析的根，不提供完整隔离。容器通常创建私有 mount namespace，准备 rootfs、`pivot_root`，设置只读/遮罩路径，再挂载受控的 `/proc`、`/dev` 等。

mount propagation 决定 mount 事件是否跨 namespace 传播。忽略 shared/private 关系可能把容器 mount 泄漏到宿主或让卸载行为异常。

镜像层可由 overlay filesystem 合并为 lower/upper/work 层；写时复制节省空间，但 metadata-heavy workload、copy-up 和 inode 语义需要单独测量。

## OCI 边界

Open Container Initiative 维护三类规范：

- Image Specification：manifest、config 与 layer 内容；
- Distribution Specification：registry 传输接口；
- Runtime Specification：解包后的 bundle 如何创建和运行。

高层编排器、容器引擎和 low-level runtime 的职责不同。镜像是内容与配置描述，不是正在运行的容器；runtime bundle 是本地执行输入；容器是受状态机管理的进程集合。

```text
image pull -> unpack -> runtime bundle
           -> create -> created
           -> start  -> running
           -> exit   -> stopped
           -> delete
```

具体合法转换和 hook 时机以 OCI Runtime Specification 版本为准。

## 容器与虚拟机

容器内进程直接使用宿主内核；虚拟机通常由 guest kernel 管理自身用户态，并通过 hypervisor 访问虚拟硬件。

| 边界 | 容器 | 虚拟机 |
| --- | --- | --- |
| 内核 | 与宿主共享 | guest 独立 |
| 启动/密度 | 通常轻量 | 通常更高开销 |
| syscall 攻击面 | 直接到宿主内核 | 先到 guest 内核 |
| 设备模型 | namespace/cgroup/device policy | 虚拟设备或直通 |
| 隔离强度 | 依内核与策略 | 增加 hypervisor 边界 |

这不是绝对安全等级排序。microVM、用户态内核、机密计算和设备直通形成更多组合，威胁模型必须具体。

## 一个最小的观察实验

以下命令需要 Linux 的 `unshare`，用户 namespace 能否创建取决于内核/发行版策略：

```bash
unshare --user --map-root-user --mount --pid --fork \
  sh -c 'mount -t proc proc /proc; echo "pid=$$"; id; cat /proc/self/cgroup'
```

它展示用户、mount、PID namespace 的组合，不是安全容器：没有独立 rootfs、cgroup 限制、capability 收紧、seccomp、LSM、设备策略和网络配置。

可从宿主观察边界：

```bash
readlink /proc/$PID/ns/{user,mnt,pid,net,cgroup}
cat /proc/$PID/status | grep -E 'Cap(Inh|Prm|Eff|Bnd|Amb)'
cat /proc/$PID/cgroup
```

namespace inode 相同表示同一 namespace 实例；它不说明其中策略足够安全。

## 资源压力与失败语义

### CPU

quota 用尽后任务被 throttle，表现为周期性尾延迟；平均 CPU 使用率可能低于一核，却仍因短周期突发触顶。

### 内存

cgroup reclaim、`memory.high`、swap 和 `memory.max` 共同决定压力。cgroup OOM 可杀组内进程；是否把整个工作负载作为单元终止取决于配置。

### PID

`pids.max` 防 fork bomb，但限制命中后 thread/process 创建返回错误。运行时必须把错误传播，而不是进入无休止重试。

### I/O

块 I/O controller 只覆盖特定路径和设备；page cache 写入与真正 writeback 之间有时间差。必须用业务延迟、PSI 和设备队列共同验证限制效果。

## 容器不是可复现性的充分条件

镜像 digest 固定了镜像内容，却没有固定：

- CPU/ISA 和微码；
- 宿主内核、cgroup/namespace 行为；
- 外部服务、DNS 和时间；
- 挂载内容、secret 与设备；
- 调度、NUMA 和资源压力；
- 可变 tag 指向的 manifest。

可复现构建还需固定输入、工具链和构建过程；可复现运行需记录宿主与外部环境。

## 失败模式

- 只用 namespace，不设资源边界；
- 把 chroot 当安全 sandbox；
- 默认保留过宽 capability；
- 把 seccomp allowlist 当完整授权模型；
- 容器 PID 1 不回收子进程或不转发信号；
- 使用可变 image tag 代替 digest；
- 把容器内 root 当宿主 root，也把 user namespace root 当完全无害；
- 挂载宿主 socket/设备后仍宣称强隔离；
- 只看使用量，不看 throttling、PSI 和 OOM 事件。

## 跨层连接

- namespace 通过 [clone](process-thread.md) 改变资源共享；
- CPU quota、亲和性与[调度](scheduling.md)相互作用；
- memory cgroup 与[虚拟内存回收](virtual-memory.md)相互作用；
- 容器网络仍依赖普通网络协议与队列；容器特定攻防材料属于独立安全知识域。

## Reference

- [Linux namespaces(7)](https://www.man7.org/linux/man-pages/man7/namespaces.7.html)
- [Linux Control Group v2](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)
- [Linux capabilities(7)](https://www.man7.org/linux/man-pages/man7/capabilities.7.html)
- [Linux seccomp(2)](https://www.man7.org/linux/man-pages/man2/seccomp.2.html)
- [Linux mount namespaces](https://www.man7.org/linux/man-pages/man7/mount_namespaces.7.html)
- [Open Container Initiative Runtime Specification](https://github.com/opencontainers/runtime-spec)
- [Open Container Initiative Image Specification](https://github.com/opencontainers/image-spec)
- [Open Container Initiative Distribution Specification](https://github.com/opencontainers/distribution-spec)
- [Linux Overlay Filesystem](https://www.kernel.org/doc/html/latest/filesystems/overlayfs.html)
