# 文件系统

文件系统把持久介质上的块、日志和校验结构组织成目录、名字、文件与属性。应用看到的是 pathname 和文件描述符；内核 VFS 把统一接口分派给具体文件系统；page cache 和 writeback 又把“写入内存”与“稳定落盘”分开。

## 路径、dentry、inode 与 open file description

一次 `open("/a/b")` 大致经历：

1. 从根目录或当前目录开始解析组件；
2. dentry cache 命中则复用名字到 inode 的关联；
3. miss 时调用具体文件系统 lookup；
4. 检查目录执行权限、mount、symlink 等规则；
5. 创建 open file description，记录偏移和状态；
6. 在进程文件描述符表中分配整数 fd。

几个对象不能混淆：

- pathname 是一次查找输入，可随后被 rename/unlink；
- dentry 是内存中的名字—inode 关系缓存；
- inode 表示文件系统对象身份和元数据；
- open file description 是一次打开实例；
- fd 是进程表中指向打开实例的索引。

`dup` 和 `fork` 后的 fd 可以共享 open file description，因此共享文件偏移。unlink 名字后，只要仍有打开引用，inode 和数据仍可继续存在。

## page cache

普通 buffered I/O 通常先与 page cache 交互：

```text
write -> copy/update page cache -> mark dirty -> return
                                  |
                                  v
                        background writeback -> device
```

`write` 成功只表示数据已被内核接受，不表示介质已经稳定保存。`read` 命中 page cache 时无需设备 I/O；miss 才需读取并等待。

`mmap` 与 `read/write` 可共享同一 file-backed page cache。二者的同步、可见性和错误报告方式不同，不能只按“少一次 copy”决定 API。

## 块分配与 extent

现代文件系统常用 extent 表示连续逻辑块到物理块范围的映射，减少大文件元数据并改善顺序 I/O。延迟分配让文件系统在 writeback 时获得更多全局信息，从而选择更连续的空间，但也把空间不足等错误推迟。

稀疏文件允许逻辑范围没有实际块；读 hole 返回零。文件长度、已分配块和物理连续性是不同维度。

## crash consistency

崩溃可能发生在任意持久化边界之间。文件系统日志主要保护自身元数据不变式，不自动把多次应用写变成业务事务。

考虑更新配置：

```text
write config.new
fsync(config.new)
rename(config.new, config)
fsync(parent_directory)
```

这是一种常见 same-filesystem 替换协议：

1. 在同一目录创建临时文件；
2. 完整写入并检查错误；
3. `fsync` 临时文件，使数据和必要元数据稳定；
4. `rename` 原子替换目录项；
5. `fsync` 父目录，使 rename 持久化。

它不处理跨目录/跨文件系统 rename，也不自动保留旧文件权限、ACL、xattr。设备写缓存与电源故障保证仍取决于内核、文件系统和硬件协议。

## 一个完整替换实现

下面是 Linux/POSIX C11 的简化实现。它在当前目录用固定临时名，实际库代码还应避免并发命名冲突并保留目标元数据。

```c
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
static int write_all(int fd, const void *buf, size_t n) {
    const char *p = buf;
    while (n) {
        ssize_t k = write(fd, p, n);
        if (k > 0) { p += k; n -= (size_t)k; continue; }
        if (k < 0 && errno == EINTR) continue;
        return -1;
    }
    return 0;
}
int main(void) {
    const char data[] = "version=2\n";
    int fd = open("config.tmp", O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0644);
    if (fd < 0) { perror("open temp"); return 1; }
    if (write_all(fd, data, sizeof data - 1) < 0 || fsync(fd) < 0 || close(fd) < 0) {
        perror("write/fsync"); unlink("config.tmp"); return 1;
    }
    if (rename("config.tmp", "config") < 0) { perror("rename"); unlink("config.tmp"); return 1; }
    int dir = open(".", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (dir < 0 || fsync(dir) < 0 || close(dir) < 0) { perror("fsync dir"); return 1; }
}
```

固定临时名使并发更新者冲突而不是相互覆盖，这是刻意的安全退化；生产实现可用随机、`mkstemp` 或平台支持的 `O_TMPFILE`，但必须重新证明 link/rename 和 crash 行为。

## journaling 与 copy-on-write

### journaling

先把即将进行的元数据或数据更新记录到 journal，再提交到主结构。恢复时根据已提交事务重放。writeback、ordered、data-journaling 等模式对数据与元数据顺序保证不同，不能只说“有日志就不会丢数据”。

### copy-on-write 文件系统

修改时写新块，再以树根/元数据提交切换到新版本，有利于快照和校验。它仍需处理写放大、空间压力、碎片、设备 flush 与多设备一致性。

二者都是文件系统内部 crash consistency 机制；数据库的 WAL/事务有自己的原子性与恢复协议。

## direct I/O、DAX 与绕过 cache

`O_DIRECT` 的对齐和支持规则依文件系统、内核与设备而变。它可减少 page cache 双重缓存和 copy，却把对齐、调度、缓存管理与短 I/O 复杂度交给应用。

DAX 可让持久内存绕过 page cache 建立直接映射，但 CPU cache 与持久化域之间仍需 flush/fence 协议。普通 `msync`、`fsync` 或持久内存库的具体保证要以平台文档为准。

## 目录操作的并发语义

rename 在规定条件下对名字替换具有原子可见性，但读者打开旧名字获得的 fd 仍引用旧对象。open 后应基于 fd 操作，避免重复解析受并发 rename/symlink 影响的 pathname。

安全敏感或竞态敏感的路径解析可使用 Linux `openat2` 的解析限制；这是 Linux 扩展，不是 POSIX 通用接口。

## 测量文件系统

分层观察：

- 应用：请求 latency、字节数、fsync latency；
- VFS/page cache：hit、dirty、writeback、readahead；
- 文件系统：extent 分配、journal、锁与回收；
- block layer：queue depth、merge、completion；
- 设备：media latency、cache、GC、错误。

Linux 入口：

```bash
strace -T -e openat,read,write,fsync,fdatasync,rename ./program
cat /proc/meminfo | grep -E 'Cached|Dirty|Writeback'
cat /proc/pressure/io
```

`strace` 显示系统调用时间，但异步 writeback 可能发生在别的线程；块设备 latency 也不等于应用 fsync latency。需要用 tracepoint 对齐跨层时间线。

## 失败模式

- `write` 返回就认为已持久化；
- 只 fsync 文件，不 fsync 新增/rename 所在目录；
- 忽略短写、`EINTR` 与延迟错误；
- 多线程共享文件偏移却假定每次 write 目标位置独立；
- 用 pathname 多次检查再打开，产生 TOCTOU；
- 把 unlink 当立即擦除内容；
- 用 benchmark 的顺序大块吞吐代表小随机 fsync；
- direct I/O 与 buffered I/O 混用却不管理一致性；
- 文件系统 journal 等同应用事务。

## 跨层连接

- file-backed 页和回收见[虚拟内存](virtual-memory.md)；
- 设备队列与完成见[I/O、中断与 DMA](io-interrupt-dma.md)；
- fd 与 open file description 的归属见[进程与线程](process-thread.md)；
- 多任务异步文件操作进入[异步 I/O 与事件循环](../concurrency/async-event-loop.md)。

## Reference

- [The Open Group: File and Directory Operations](https://pubs.opengroup.org/onlinepubs/9799919799/functions/contents.html)
- [Linux Kernel Documentation: Virtual File System](https://www.kernel.org/doc/html/latest/filesystems/vfs.html)
- [Linux Kernel Documentation: Pathname Lookup](https://www.kernel.org/doc/html/latest/filesystems/path-lookup.html)
- [Linux Kernel Documentation: ext4](https://www.kernel.org/doc/html/latest/filesystems/ext4/)
- [XFS Filesystem Structure](https://kernel.org/doc/html/latest/filesystems/xfs/xfs-delayed-logging-design.html)
- [Linux fsync(2)](https://www.man7.org/linux/man-pages/man2/fsync.2.html)
- [Linux openat2(2)](https://www.man7.org/linux/man-pages/man2/openat2.2.html)
- [McKusick et al., A Fast File System for UNIX](https://doi.org/10.1145/989.990)
- [Rosenblum and Ousterhout, The Design and Implementation of a Log-Structured File System](https://doi.org/10.1145/121132.121137)
