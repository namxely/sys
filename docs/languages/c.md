# C：抽象机、对象与系统边界

C 常被称为“可移植汇编”，但这个比喻只说中了它贴近机器的一面。真正决定程序含义的不是某颗 CPU，而是语言标准定义的 **abstract machine**：对象何时存在、表达式按什么规则求值、哪些访问可以别名、哪些并发执行有序。编译器再把这份契约映射到 ABI、指令集和操作系统接口。越接近系统底层，越需要把这几层分开。

本文以 [ISO/IEC 9899:2024](https://www.iso.org/standard/82075.html) 为语言边界，并用 POSIX Issue 8、System V AMD64 ABI 与 Clang 工具链说明一种常见实现；后三者都不是 ISO C 的组成部分。

## 从可移植系统语言到优化契约 {#history}

早期 C 的目标，是让 Unix 内核的大部分代码脱离特定机器的汇编，同时保留数组、指针和位运算带来的直接控制。随着处理器流水线、寄存器分配和跨过程优化变得复杂，语言不能只描述“机器通常怎么做”，还必须告诉实现哪些程序变换保持语义。

这就是未定义行为的重要历史背景。若有符号溢出、越界访问或无序数据竞争必须保留某种具体的机器结果，编译器就很难做循环优化、别名分析和指令重排。C 的选择是：为可移植程序规定可观察行为，把一部分越界程序排除在契约之外。C11 又加入原子类型和线程间顺序，使并发程序能在弱内存硬件上表达可移植同步；2024 年发布的第五版 C 标准继续整理这套抽象机，而没有把编译、链接、装载或系统调用机制写进语言本身。

因此，阅读一段 C 程序应依次问：

1. 它在 ISO C 抽象机中是否有定义？
2. 实现选择了怎样的数据模型、对象文件格式和 ABI？
3. 库与操作系统为 I/O、线程和进程提供了什么额外契约？
4. 生成代码在目标微架构上如何执行？

跳过第一问直接看汇编，容易把编译器利用未定义行为后的结果误认为语言规则；跳过第二、三问，又会把一次平台实验误认为可移植保证。

## 对象不是一串无条件可读的字节 {#object-model}

对象占据一段 storage，具有类型、大小、对齐和 lifetime。[WG14 N3096 的对象与表示规则](https://www.open-std.org/jtc1/sc22/wg14/www/docs/n3096.pdf)区分 object representation 与 value representation：除位域外，一个对象由若干字节组成，其中可能包含 padding。`unsigned char`、`char` 或 `memcpy` 可以观察和复制对象表示，但“能复制字节”不等于“任意字节模式对任意类型都是有效值”。

例如结构体的两个成员之间可能有 padding：

```c
#include <stddef.h>
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <string.h>
typedef struct {
    uint8_t tag;
    uint32_t value;
} Item;
int main(void) {
    Item a = {.tag = 7, .value = UINT32_C(0x12345678)};
    unsigned char bytes[sizeof a];
    memcpy(bytes, &a, sizeof a);
    Item b;
    memcpy(&b, bytes, sizeof b);
    printf("size=%zu value=%" PRIu32 "\n", sizeof a, b.value);
    return b.tag != 7 || b.value != UINT32_C(0x12345678);
}
```

这段代码复制同一类型对象的完整表示是合法的，但不要由此推出：

- `sizeof(Item)` 必然是 5；
- padding 的内容适合拿来做哈希或 `memcmp` 等价性；
- 它可直接作为跨机器、跨编译器的网络格式；
- 任意外部字节都能先强转为 `Item *` 再解引用。

稳定的外部格式应逐字段规定字节序、宽度和边界。对齐不足的缓冲区、对象 lifetime 尚未开始的 storage、已经释放的地址以及越过数组对象边界的指针，都不能仅凭“地址数值看起来有效”恢复合法性。

### 指针同时携带访问资格

在抽象机中，指针不只是一个可打印的整数。它还与所指对象、数组边界、对齐和 lifetime 有关。常见错误包括：

- 返回自动存储期局部对象的地址；
- `realloc` 后继续使用旧指针；
- 形成或解引用越过数组允许范围的指针；
- 通过不兼容类型的左值访问对象；
- 把任意整数转换成指针后假定一定可解引用。

“one-past”指针可以用于比较和循环终止，却不能解引用。两个数值相同的指针也可能来自不同生命周期；内存分配器复用地址不会让旧指针重新有效。现代编译器的 provenance 讨论，正是在澄清这种“地址数值”与“合法访问路径”的差异。

## 别名、有效类型与优化 {#aliasing}

编译器若能证明两个访问不可能指向同一对象，就可把加载留在寄存器、改变循环顺序或向量化。C 的兼容类型和 aliasing 规则为这类证明提供依据；字符类型访问对象表示是重要例外。

下面这种类型双关不应通过不兼容指针完成：

```c
float f = 1.0f;
uint32_t bits;
memcpy(&bits, &f, sizeof bits);
```

只要两边大小相同，`memcpy` 是表达表示复制的清晰方式，优化器通常会把固定大小复制消成寄存器移动。使用 union 读取非最后写入成员的语义还涉及标准的特定规则和实现扩展；跨编译器代码不应把某个工具链的习惯当成普遍保证。

`restrict` 则是程序员主动给出的访问承诺。它能帮助优化热点循环，但违反关联对象在执行期的访问约束会导致未定义行为。把它机械地加到所有指针参数上，往往是在把潜在性能收益换成更难发现的正确性缺陷。

## 未定义、未指定与实现定义 {#undefined-behavior}

三类“标准没有给单一结果”的情形不能混为一谈：

- **implementation-defined**：实现必须选择并记录，例如普通 `char` 是否有符号；
- **unspecified**：实现可在允许集合中选择，不必记录每次选择，例如某些求值次序；
- **undefined behavior（UB）**：标准不再对该执行提出要求，例如有符号溢出、越界解引用或数据竞争。

UB 不是“运行后随机出错”，而是源程序已失去语言保证。一个检查也可能因此前的 UB 假设而被优化掉：

```c
int greater(int x) {
    return x + 1 > x;
}
```

若 `x == INT_MAX`，`x + 1` 的数学结果无法由 `int` 表示，执行触发有符号溢出 UB；对所有有定义的执行，函数可被优化为恒真。若需要模 $2^N$ 算术，应使用合适的无符号类型并明确转换；若需要检测溢出，应先检查边界或使用编译器提供的 checked arithmetic 接口。

### 把外部字节变成值

下面的解析器只在边界检查后逐字节组合一个 little-endian `uint32_t`，不依赖未对齐加载、主机字节序或对象别名：

```c
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
static bool read_u32le(const unsigned char *p, size_t n, size_t off, uint32_t *out) {
    if (off > n || n - off < 4) return false;
    *out = (uint32_t)p[off] |
           (uint32_t)p[off + 1] << 8 |
           (uint32_t)p[off + 2] << 16 |
           (uint32_t)p[off + 3] << 24;
    return true;
}
int main(void) {
    const unsigned char packet[] = {0x78, 0x56, 0x34, 0x12};
    uint32_t x = 0;
    if (!read_u32le(packet, sizeof packet, 0, &x)) return 1;
    printf("%08" PRIx32 "\n", x);
    return x != UINT32_C(0x12345678);
}
```

检查写成 `off > n || n - off < 4`，是为了避免 `off + 4` 本身发生 `size_t` 回绕。系统代码的许多漏洞并不来自复杂算法，而是把“数学上正确”的边界条件直接翻译为有限宽度整数表达式。

## ABI：语言之外的二进制协议 {#abi}

ISO C 不规定寄存器如何传参、结构体怎样返回、符号如何命名，也不规定 ELF、Mach-O 或 PE。ABI 才规定已编译模块之间的这些细节。以 [System V AMD64 ABI](https://gitlab.com/x86-psABIs/x86-64-ABI) 为例，整数与指针参数通常先使用通用寄存器，浮点参数使用向量寄存器，大对象可能经内存间接传递；栈对齐、callee-saved 寄存器和变参规则也属于调用协议。

一个看似简单的声明：

```c
struct Pair { long x, y; };
struct Pair add(struct Pair a, struct Pair b);
```

在 LP64 与 LLP64 数据模型中，`long` 宽度可能不同；在不同 ABI 中，参数和返回值的分解方式也可能不同。公开二进制接口需要同时固定：

- 目标架构、操作系统与 ABI 版本；
- 数据模型、对齐和结构体布局；
- 编译器扩展、可见性与 calling-convention 属性；
- 所有权、分配与释放由哪一侧负责；
- 错误是返回码、`errno`、回调还是进程级失败。

跨语言 FFI 适合暴露固定宽度整数、显式长度、opaque handle 和小型 C 函数表，而不适合直接暴露编译器相关结构体或让两侧混用 allocator。

## 并发：原子性不等于发布 {#concurrency}

C11 把 `_Atomic`、memory order 和 happens-before 带入语言。[WG14 N3096 的 multi-threaded executions 规则](https://www.open-std.org/jtc1/sc22/wg14/www/docs/n3096.pdf)规定：若两个线程访问同一内存位置，至少一个是写，访问不是原子的且没有 happens-before 顺序，便形成 data race；整个程序执行具有未定义行为。`volatile` 不提供互斥、原子性或线程间可见性，它主要服务于标准规定的易变访问场景和实现定义的 MMIO 等接口。

release/acquire 可以把普通数据安全地从生产者发布给消费者：

```c
#include <assert.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdatomic.h>
static int payload;
static atomic_bool ready;
static void *producer(void *unused) {
    (void)unused;
    payload = 42;
    atomic_store_explicit(&ready, true, memory_order_release);
    return NULL;
}
static void *consumer(void *unused) {
    (void)unused;
    while (!atomic_load_explicit(&ready, memory_order_acquire)) {}
    assert(payload == 42);
    return NULL;
}
int main(void) {
    pthread_t a, b;
    atomic_init(&ready, false);
    if (pthread_create(&a, NULL, producer, NULL) != 0) return 1;
    if (pthread_create(&b, NULL, consumer, NULL) != 0) return 1;
    pthread_join(a, NULL);
    pthread_join(b, NULL);
    return 0;
}
```

当 acquire load 读到 release store 写入的值时，二者建立 synchronizes-with；生产者对 `payload` 的写经传递 happens-before 消费者的读。若把两个操作都改为 relaxed，`ready` 仍不会发生撕裂，但它不再发布周围的普通写。

选择顺序时先写出需要的边：

- `relaxed`：该原子对象的修改顺序与原子读写，不携带旁边数据；
- `release/acquire`：一端发布，此后另一端获取；
- `seq_cst`：在上述性质外参加单一全序，推理最直接；
- fence：只有与具体原子操作组成规定关系时才有意义。

无锁并不天然更快。争用缓存行、compare-exchange 重试、ABA、回收悬垂节点和跨 NUMA 流量，都可能让锁成为更稳定的选择。进一步可结合[原子操作与内存模型](../architecture/atomics-memory-model.md)和[无锁结构与 RCU](../concurrency/lock-free-rcu.md) 理解。

## 从库调用到系统调用 {#syscall-boundary}

`printf`、`malloc` 和 `fopen` 是 C 标准库接口；`read`、`write`、`fork`、`mmap` 和 socket API 主要来自 POSIX 或具体操作系统。普通函数名不意味着“一次调用就对应一条系统调用”：libc 可以缓冲、重试、转换参数，动态链接器也会参与符号解析。

[POSIX Issue 8](https://pubs.opengroup.org/onlinepubs/9799919799/) 中 `read`/`write` 的正确循环必须面对：

- 成功传输字节数小于请求长度；
- 信号中断与 `EINTR`；
- non-blocking fd 的 `EAGAIN` / `EWOULDBLOCK`；
- EOF、对端关闭和永久错误；
- `size_t`、`ssize_t` 与内核单次传输上限。

```c
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <limits.h>
#include <stddef.h>
#include <unistd.h>
static int write_all(int fd, const unsigned char *p, size_t n) {
    while (n != 0) {
        size_t chunk = n > (size_t)SSIZE_MAX ? (size_t)SSIZE_MAX : n;
        ssize_t k = write(fd, p, chunk);
        if (k > 0) {
            p += (size_t)k;
            n -= (size_t)k;
        } else if (k < 0 && errno == EINTR) {
            continue;
        } else {
            return -1;
        }
    }
    return 0;
}
int main(void) {
    static const unsigned char msg[] = "ok\n";
    return write_all(STDOUT_FILENO, msg, sizeof msg - 1) != 0;
}
```

这仍是阻塞 fd 的最小版本；对 non-blocking fd，遇到 `EAGAIN` 后应交还事件循环等待可写，而不是忙等。详见 [socket 与 I/O 多路复用](../network/sockets-io.md)。

## 失败模式与测量闭环 {#measurement}

系统级 C 程序应把“语言、ABI、OS、硬件”分别观测：

```sh
cc -std=c17 -Wall -Wextra -Wconversion -Wshadow -O2 app.c
cc -std=c17 -O1 -g -fsanitize=address,undefined app.c
cc -std=c17 -O1 -g -fsanitize=thread concurrent.c
cc -std=c17 -O2 -S app.c -o app.s
```

- warnings 暴露可疑转换，却不是证明；
- [AddressSanitizer](https://clang.llvm.org/docs/AddressSanitizer.html) 检查已执行路径上的多类越界和 use-after-free；
- [UndefinedBehaviorSanitizer](https://clang.llvm.org/docs/UndefinedBehaviorSanitizer.html) 插桩若干 UB 类别，但并不覆盖全部语言约束；
- [ThreadSanitizer](https://clang.llvm.org/docs/ThreadSanitizer.html) 动态寻找数据竞争，未执行的路径仍未知；
- 汇编或 LLVM IR 能说明当前编译器、选项和目标的代码生成，不能反向扩展语言契约。

测性能时还要记录编译器版本、完整 flags、目标 ISA、输入分布、CPU 频率、缓存冷热和重复次数。一次 `-O0` 调试执行既不能代表优化构建，也不宜用于推断未定义程序“通常可用”。

### 跨层排错顺序

1. 用 sanitizers、静态分析和最小复现检查语言层；
2. 用 `readelf`、`nm`、`objdump` 或平台等价工具核对符号、重定位和 ABI；
3. 用 `strace`、DTrace 或 eBPF 观察库与内核边界；
4. 用采样 profiler、PMU 和硬件计数器定位真正热点；
5. 回到源代码修改契约，而不是只在汇编症状上打补丁。

这条路径把 C 的优势放在正确位置：它允许程序精确表达布局和成本，但不会替程序员自动维护对象、并发与系统边界。

## Reference

- [ISO/IEC 9899:2024 — Programming languages — C](https://www.iso.org/standard/82075.html)
- [WG14 N3096 — C23 committee draft](https://www.open-std.org/jtc1/sc22/wg14/www/docs/n3096.pdf)
- [IEEE Std 1003.1-2024 / POSIX.1-2024, Issue 8](https://pubs.opengroup.org/onlinepubs/9799919799/)
- [System V Application Binary Interface — AMD64 Architecture Processor Supplement](https://gitlab.com/x86-psABIs/x86-64-ABI)
- [Clang AddressSanitizer documentation](https://clang.llvm.org/docs/AddressSanitizer.html)
- [Clang UndefinedBehaviorSanitizer documentation](https://clang.llvm.org/docs/UndefinedBehaviorSanitizer.html)
- [Clang ThreadSanitizer documentation](https://clang.llvm.org/docs/ThreadSanitizer.html)
- [Linux man-pages — system calls overview](https://www.man7.org/linux/man-pages/man2/syscalls.2.html)
