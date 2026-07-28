# 进程与线程

进程不是“正在运行的程序文件”，而是一组受保护资源与执行状态的容器；线程是其中可被独立调度的执行流。同一程序文件可产生多个进程，一个进程也可拥有多个线程。

## 把进程拆开

以 Unix/POSIX 与 Linux 为坐标，一个进程通常关联：

- 虚拟地址空间及其映射；
- 一个或多个线程的寄存器、栈与调度状态；
- 文件描述符表和当前目录；
- 信号处置、凭据、资源限制；
- 父子关系、进程组和会话；
- namespace 与 cgroup 归属。

这些资源并非都嵌在一个“大进程对象”里。Linux `task_struct` 表示可调度任务，各类资源通过指针引用并可按 clone flags 共享。进程与线程因而更像共享关系的不同组合。

## 线程的最小状态

调度线程至少需要：

- 通用寄存器、PC/SP 与状态寄存器；
- 内核栈和内核调度状态；
- TLS 基址；
- 信号掩码与待处理状态；
- 浮点/向量等扩展状态；
- 调度类、优先级、亲和性与统计。

上下文切换不只保存寄存器。新线程工作集可能不在 cache/TLB 中，分支历史也不同；频繁迁移还会改变 NUMA 局部性。

## `fork`：复制视图，不复制所有字节

POSIX `fork()` 创建调用进程的副本；Linux 通常用 copy-on-write 共享物理页：

1. 为子进程建立新的地址空间元数据；
2. 父子 PTE 指向相同物理页并去掉写权限；
3. 任一方写入时触发 protection fault；
4. 内核分配新页、复制内容并更新该方 PTE；
5. 完成 TLB 同步后重试写指令。

`fork` 后父子文件描述符通常引用同一个 open file description，因此共享文件偏移和状态标志。它们的描述符表本身可以独立关闭或替换条目。

## `exec`：保留身份，替换程序映像

成功 `execve` 不创建新进程；它用新程序替换当前地址空间、栈和入口点，PID 仍保持。许多属性保留，部分信号处置和映射被重置，带 `FD_CLOEXEC` 的描述符被关闭。

`fork` + `exec` 的分工使 shell 能在 exec 前完成重定向、管道、凭据和进程组配置。

## 一个正确等待的 `fork/exec`

下面是 POSIX.1-2008 / Linux 可编译 C11 示例。它处理 `EINTR`，并把 exec 失败通过 `_exit` 结束，避免刷新父进程复制来的 stdio 缓冲。

```c
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <unistd.h>
extern char **environ;
int main(void) {
    pid_t pid = fork();
    if (pid < 0) { perror("fork"); return 1; }
    if (pid == 0) {
        char *const argv[] = {"/bin/echo", "hello", NULL};
        execve(argv[0], argv, environ);
        perror("execve");
        _exit(127);
    }
    int status;
    while (waitpid(pid, &status, 0) < 0) {
        if (errno == EINTR) continue;
        perror("waitpid"); return 1;
    }
    if (WIFEXITED(status)) return WEXITSTATUS(status);
    if (WIFSIGNALED(status)) return 128 + WTERMSIG(status);
    return 1;
}
```

在严格 POSIX 环境可显式构造环境数组或使用 `execv`；`environ` 的声明方式依实现头文件约定。

## Linux `clone`

Linux `clone`/`clone3` 通过 flags 选择共享边界：

- `CLONE_VM`：共享地址空间；
- `CLONE_FILES`：共享文件描述符表；
- `CLONE_FS`：共享当前目录等 fs 信息；
- `CLONE_SIGHAND`：共享信号处置；
- `CLONE_THREAD`：进入同一线程组；
- `CLONE_NEW*`：创建 namespace。

普通应用应优先使用 pthread 或语言运行时；手写 clone 还要正确设置线程栈、TLS、退出通知和信号语义。

## 线程共享什么

同进程线程通常共享代码、heap、全局变量、映射和文件描述符；每个线程有自己的寄存器、栈、TLS、调度状态和信号掩码。共享地址空间使通信便宜，也意味着任一线程的越界写可破坏整个进程。

POSIX thread 创建：

```c
#include <pthread.h>
#include <stdio.h>
static void *worker(void *arg) {
    long id = *(long *)arg;
    printf("worker %ld\n", id);
    return NULL;
}
int main(void) {
    pthread_t t;
    long id = 1;
    int e = pthread_create(&t, NULL, worker, &id);
    if (e) return 1;
    return pthread_join(t, NULL) != 0;
}
```

这里 `id` 在 `join` 前一直存活。若把循环中的局部变量地址交给多个线程，必须证明每个线程看到的对象身份和生命周期正确。

## 进程状态

一个实用状态图：

```text
new -> runnable -> running -> sleeping
          ^           |          |
          |           v          |
          +------ preempt <------- wakeup
running -> exited -> zombie -> reaped
```

zombie 已经不执行，也不占用户地址空间，保留的是退出状态和少量身份信息，等待父进程 `wait`。父进程不回收会积累僵尸；孤儿由合适的 subreaper/init 机制接管。

不可中断 sleep 在 Linux 进程状态中表示特定内核等待语义，不等于“进程死锁”，需结合内核栈和等待事件判断。

## 信号与多线程

信号可以面向进程或特定线程；处置通常进程共享，signal mask 每线程独立。异步 signal handler 只能安全调用 async-signal-safe 函数。锁、分配器和大多数 C++ 运行时操作都不安全。

多线程程序常选择：

1. 在所有工作线程屏蔽一组信号；
2. 用专门线程通过 `sigwait` 同步接收；
3. 将事件转成普通队列或取消请求。

这比在异步 handler 中执行复杂逻辑更可审计。

## 创建与切换成本

成本来源包括：

- 内核对象、页表与栈；
- copy-on-write 元数据与后续 fault；
- TLS 和运行时初始化；
- 调度队列与负载均衡；
- cache/TLB 冷却；
- 父子或线程间同步。

线程池减少重复创建成本，但会引入队列、背压、任务生命周期和过度订阅。协程降低用户态等待的栈与切换成本，却不会消除真正的 CPU 工作或内核 I/O，见[协程](../concurrency/coroutines.md)。

## 怎样观察

Linux 可组合：

```bash
ps -eLo pid,tid,ppid,psr,stat,comm
cat /proc/$PID/status
cat /proc/$PID/maps
strace -f -e clone,clone3,execve,wait4 ./program
perf sched timehist
```

`strace` 会改变时序，`/proc` 是瞬时快照，`perf sched` 依赖 trace 权限。诊断上下文切换时同时记录 voluntary/involuntary、runqueue delay 和迁移，而不是只看总次数。

## 失败模式

- `fork` 后在多线程子进程中调用非 async-signal-safe 逻辑再 exec；
- 子进程 exec 失败后调用 `exit`，重复刷新缓冲；
- 忘记 wait，积累 zombie；
- 把 PID 当永久身份，忽略复用；
- 在线程结束前释放传入参数；
- 把线程安全等同于 signal handler 安全；
- 用进程数或线程数直接推断实际并行度；
- 把 Linux clone flags 当 POSIX 进程定义。

## 跨层连接

- runnable 线程如何获 CPU，见[调度](scheduling.md)；
- 地址空间和 copy-on-write，见[虚拟内存](virtual-memory.md)；
- 正确共享内存需遵守[原子与内存模型](../architecture/atomics-memory-model.md)；
- namespace 与 cgroup 组合为[容器隔离](isolation-containers.md)。

## Reference

- [The Open Group: fork](https://pubs.opengroup.org/onlinepubs/9799919799/functions/fork.html)
- [The Open Group: exec family](https://pubs.opengroup.org/onlinepubs/9799919799/functions/exec.html)
- [The Open Group: pthread_create](https://pubs.opengroup.org/onlinepubs/9799919799/functions/pthread_create.html)
- [Linux clone(2)](https://www.man7.org/linux/man-pages/man2/clone.2.html)
- [Linux proc_pid_status(5)](https://www.man7.org/linux/man-pages/man5/proc_pid_status.5.html)
- [MIT xv6 Book: Chapter 4 Traps and System Calls, Chapter 7 Scheduling](https://pdos.csail.mit.edu/6.1810/2025/xv6/book-riscv-rev5.pdf)
