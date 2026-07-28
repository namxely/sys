# Java 与 JVM：从字节码契约到运行时优化

Java 的关键设计不是“所有代码都解释执行”，而是把源语言与执行引擎之间切开：编译器产生结构化的 class file，虚拟机先装载、验证和链接，再选择解释、即时编译（JIT）或其他执行策略。这个分层让同一份字节码能跨平台，也让运行时根据真实类型、调用频率和堆行为持续优化。

本文以 [Java SE 25 规范集](https://docs.oracle.com/en/java/javase/25/docs/specs/index.html) 为语言与虚拟机契约，核验至 2026-07-28；HotSpot、JOL、JFR 和具体垃圾收集器只作为 OpenJDK 实现实例。JVM 规范没有固定对象头大小、GC 算法、JIT 层级或机器码形状。

## 为什么要在源语言与机器之间加一层 {#history}

20 世纪 90 年代的 Java 把可移植性、动态链接、自动内存管理和运行时检查组合起来。它没有要求每个源程序直接绑定一个 CPU ABI，而是规定可验证的 class file 与 JVM 抽象机。class file 自带类型、方法、字段、常量池和结构化属性；运行时可在类真正需要时再装载和解析。

这种选择带来两个长期结果：

1. <strong>部署契约稳定于字节码层。</strong>Java 编译器、Kotlin 等前端都可以生成 JVM class file；运行时通过相同的验证和链接规则接收它。
2. **执行策略可以演进。**[JVMS 的历史说明](https://docs.oracle.com/javase/specs/jvms/se25/html/jvms-1.html)明确 JVM 不必天然是解释器；实现可以解释、JIT 编译，也可以使用专用硬件。

早期虚拟机常把“跨平台”换成启动和峰值性能代价。HotSpot 路线用 profile-guided compilation、内联和去优化（deoptimization）化解这个矛盾：先快速开始，观察实际调用，再为热路径生成专门代码；若假设失效，则恢复到较通用的执行状态。垃圾收集也从单一停顿式方案演化为吞吐、延迟和堆规模各有侧重的多个 collector。

这段历史形成了今天的阅读方法：先判断 JLS/JVMS 保证什么，再判断某个 JDK 实现当前怎样做到。

## 三份契约：源码、class file、运行时 {#contracts}

### JLS 规定源程序

[Java Language Specification](https://docs.oracle.com/javase/specs/jls/se25/html/index.html) 定义类型系统、表达式求值、异常、线程与内存模型。源码中 `int` 固定为 32 位二进制补码语义，不会因宿主是 LP64 就变成 64 位；引用不是可做地址算术的 C 指针。

### JVMS 规定虚拟机与 class file

[JVMS Chapter 4](https://docs.oracle.com/javase/specs/jvms/se25/html/jvms-4.html) 定义 class file 的二进制格式与约束。Java SE 25 对应的 class file major version 是 69。方法体通常编码为面向 operand stack 的 bytecode；每个调用 frame 包含局部变量区、操作数栈和到当前类运行时常量池的引用。

源代码：

```java
static int twice(int x) {
    return x + x;
}
```

可能产生概念上类似的字节码：

```text
iload_0
iload_0
iadd
ireturn
```

字节码不是目标 CPU 的微操作，也不是“必须逐条解释”的指令流。它是验证与执行的可移植输入；JIT 可把整个热方法、循环或内联后的调用图编译为机器码。

### Java SE API 规定库行为

集合、I/O、并发工具、FFM 等库 API 又构成第三层契约。`HashMap` 的公开行为不能由某次对象布局实验推断；`Unsafe`、HotSpot flags 与内部类名也不自动成为 Java SE 保证。

## 类的生命线：load、link、initialize {#class-lifecycle}

[JVMS Chapter 5](https://docs.oracle.com/javase/specs/jvms/se25/html/jvms-5.html) 把类或接口的创建过程分成几个阶段：

```text
class bytes
   │
   ▼
loading ──> verification ──> preparation ──────────> initialization
                ╲               ╲                         │
                 ╲_______________╲──> resolution <────────┘
                         eager or lazy; may continue later
```

- **loading**：类加载器按 binary name 寻找 class 表示，并由字节构造 `Class` 对象；
- **verification**：检查 class file 格式、类型与控制流约束，防止构造非法栈状态或不兼容调用；
- **preparation**：为静态字段创建存储并设默认值，准备运行时数据结构；
- **resolution**：把常量池中的符号引用解析为具体类、字段或方法；实现可在允许的时点延迟解析；
- **initialization**：执行类或接口初始化方法 `<clinit>`，落实显式静态初始化。

“加载了”不等于“静态初始化已执行”。访问编译期常量、反射、首次调用静态方法、创建实例和某些 method-handle 操作触发初始化的规则不同。初始化还受锁保护；若 `<clinit>` 等待另一个反向等待的类初始化，便可能产生难以识别的死锁。

### 类加载器同时划定类型身份

运行时类型身份不仅由 binary name 决定，还包含 defining class loader。两个加载器各自定义的 `example.Plugin` 名字相同，也不是同一运行时类型。这是应用服务器、插件隔离和热部署的基础，也是 `ClassCastException` 看似“同名类型不能转换”的根源。

委派并非 JVM 规范规定的唯一算法，而是具体加载器体系的策略。设计插件系统时，应明确：

- 哪些 API 类由共同父加载器定义；
- 哪些实现类可卸载；
- thread-local、静态缓存、JMX 注册和线程是否仍持有加载器；
- native library 与 class loader 的关联如何释放。

## 验证：先证明字节码结构可执行 {#verification}

验证器不是对业务正确性的证明，而是确保代码满足 JVM 类型与控制流约束。它会检查操作数栈高度与类型在分支汇合处一致、局部变量使用正确、方法调用的 descriptor 匹配、跳转目标合法等。

把验证想成对每条指令传递一个抽象状态：

$$
S_i=(L_i, O_i)
$$

其中 $L_i$ 是局部变量类型向量，$O_i$ 是操作数栈类型序列。一条 `iadd` 要求 $O_i$ 顶部有两个 `int`，转移后弹出两项并压入一个 `int`；控制流汇合点必须存在合法的公共状态。现代 class file 的 stack map frames 帮助验证器避免从零推导所有路径。

验证通过意味着恶意字节码不能随意把整数当宿主地址解引用，但它不阻止无限循环、内存耗尽、业务越权或通过合法 API 访问敏感资源。安全性仍取决于可达 API、模块边界、进程权限和宿主配置。

## 从解释到 JIT：用证据换取专门化 {#jit}

HotSpot 通常先让代码以解释或较低成本编译形态运行，同时记录调用计数、分支概率、receiver 类型和循环热点。热方法可进入更高优化层级：

```text
bytecode
   ├── interpreter / quick compilation
   │        └── profile: counts, types, branches
   └── optimizing compiler
            ├── inlining
            ├── escape analysis
            ├── loop and range-check optimization
            └── speculative machine code
```

动态分派原本要从对象类型寻找目标方法；若 profile 显示调用点长期只有一种 receiver，JIT 可以做 guarded inlining：

```text
if receiver.class == ObservedType:
    execute inlined body
else:
    uncommon path / deoptimize
```

这不是把动态语言规则改成静态规则。机器码携带假设和恢复元数据；新子类加载、类型分布变化或 uncommon trap 可让代码失效，运行时把执行状态重建为解释器或较低层 frame，再重新优化。

### OSR 与 safepoint

一个长循环可能在方法尚未返回时变热。On-Stack Replacement（OSR）允许执行从解释 frame 进入已编译循环，也允许去优化回到可恢复状态。GC、偏向撤销的历史机制、调试和部分运行时操作需要线程到达 safepoint 或可安全检查的位置；“停顿时间”因而不仅由标记算法决定，还受线程到达安全状态的延迟影响。

实现细节会随 JDK 改变。诊断某次优化时，应保存 JDK build、flags、汇编或编译日志；不能把一次 HotSpot 输出写成 JVM 规范事实。

## 对象布局：规范故意没有固定 {#object-layout}

Java 语言只保证字段和方法的语义，不规定对象地址、header、字段间 padding 或引用压缩。以 HotSpot 为例，对象通常需要记录 GC/锁相关状态与类元数据，并按实现对齐；数组还需要长度。Compressed ordinary object pointers、compact object headers 等选项会改变形状。

概念图可以帮助定位成本，却不是 ABI：

```text
object
├── runtime header      implementation-specific
├── class metadata ref  implementation-specific
├── instance fields
└── alignment padding
```

[Java Object Layout（JOL）](https://openjdk.org/projects/code-tools/jol/)通过运行时和 VM 信息分析对象布局，适合回答“这个 JDK、这些 flags 下为什么是这个尺寸”。它不适合支持序列化协议或 native 端硬编码 offset。

对象分配也不能简单等同于一次系统 `malloc`。常见 HotSpot 路径会从线程局部分配缓冲区推进指针，失败时才进入慢路径；对象若经 escape analysis 证明不逃逸，部分分配和字段甚至可以 scalar replacement。要判断“创建对象很贵”，应观察分配率、逃逸结果、GC 压力与生成代码，而不是数 `new` 关键字。

## 垃圾收集：回收不可达对象，不管理外部资源 {#gc}

GC 从 roots 出发追踪可达对象，释放不可达对象占据的托管堆。Java SE 不指定 collector；[JDK 25 GC Tuning Guide](https://docs.oracle.com/en/java/javase/25/gctuning/index.html) 描述 HotSpot 的多种选择及其吞吐、延迟和 footprint 取舍。

### 为什么需要代际、区域与屏障

许多工作负载呈现“大量对象很快死亡”的经验分布。分代 collector 让年轻区频繁回收，而不每次扫描全部老年代。区域化 collector 把堆拆成可独立选择和回收的 region。并发标记则把大量追踪工作移出 stop-the-world 阶段。

但并发与局部回收必须维持跨区、跨代引用信息。写入：

```java
oldObject.field = youngObject;
```

可能触发 write barrier，更新 remembered set 或 card table。读屏障、染色指针和转发表则是另一些 collector 的实现策略。屏障成本位于应用的普通读写热路径上；它们是换取并发移动和较短停顿的代价。

### GC 指标必须成组阅读

- allocation rate：每秒进入堆的字节；
- live-set：完整标记后仍可达的数据；
- pause distribution：P50 之外尤其关注 P99/P99.9；
- concurrent-cycle CPU：应用吞吐为低停顿付出的后台成本；
- promotion、humongous allocation 与 evacuation failure；
- 堆外内存、线程栈、代码缓存和 native allocation。

只增加 `-Xmx` 可能降低回收频率，也可能延长某些阶段、推高容器 RSS 或把 OOM 延迟到更难恢复的时刻。`AutoCloseable` 与 try-with-resources 仍应管理文件、socket、native handle；GC 只决定 Java 对象可达性，不能提供及时关闭语义。

## Java Memory Model：可见性来自 happens-before {#jmm}

[JLS Chapter 17](https://docs.oracle.com/javase/specs/jls/se25/html/jls-17.html) 定义线程动作与 happens-before。若两个冲突访问没有 happens-before 且至少一个是写，程序存在 data race；无数据竞争的正确同步程序获得顺序一致性的核心保证。

重要边包括：

- 对同一 monitor 的 unlock happens-before 后续 lock；
- 对同一 `volatile` 字段的写 happens-before 后续读；
- `Thread.start()` 之前的动作 happens-before 新线程中的动作；
- 线程中的全部动作 happens-before 另一线程成功从 `join()` 返回；
- 正确构造对象的 `final` 字段具有额外初始化安全保证，但构造期间泄漏 `this` 会破坏前提。

下面是一个可直接编译运行的安全发布例子：

```java
public final class Publication {
    private static final class Payload {
        final int value;
        Payload(int value) {
            this.value = value;
        }
    }
    private static volatile Payload ready;
    public static void main(String[] args) throws InterruptedException {
        Thread consumer = new Thread(() -> {
            Payload p;
            while ((p = ready) == null) Thread.onSpinWait();
            if (p.value != 42) throw new AssertionError(p.value);
        });
        Thread producer = new Thread(() -> ready = new Payload(42));
        consumer.start();
        producer.start();
        producer.join();
        consumer.join();
    }
}
```

producer 的普通构造写在 program order 中先于 volatile write；consumer 的 volatile read 读到该引用后，通过 synchronizes-with 看见此前写入。若 `ready` 是普通静态字段，循环既可能看不到更新，也可能观察到未安全发布状态；“当前 CPU 缓存最终会刷新”不是 JMM 论证。

`volatile++` 仍是 read-modify-write 三步，不能成为并发计数器。互斥不只提供可见性，还组合多个状态转换为一个不变量；`VarHandle` 和 atomic classes 适合确实需要更细粒度顺序的算法。

## JNI：越过托管边界后，契约重新开始 {#jni}

[JNI Specification](https://docs.oracle.com/en/java/javase/25/docs/specs/jni/design.html) 让 Java 调用 native library，也允许 native 代码查找类、调用方法和访问数组。它同时引入一条高风险边界：

- `JNIEnv *` 只对当前线程有效，不能缓存后交给另一线程；
- local reference 通常只在当前 native 调用范围内有效，跨调用保存要创建 global reference；
- JNI 调用可能留下 pending Java exception，native 代码必须按规范检查和传播；
- 数组/string 访问接口可能返回 copy，也可能 pin；必须用对应 release API；
- native 越界、use-after-free 或 ABI 不匹配可直接破坏进程，JVM 验证器无法隔离它。

高频细粒度 JNI 往返还会带来参数转换、状态切换和阻碍优化的成本。边界设计应尽量批量化，明确 buffer ownership、编码、线程附着、异常映射与库生命周期。

不要直接缓存普通 `jobject`：

```c
static jobject cached; /* 错误：local reference 可能在返回后失效 */
```

应在拥有有效 `JNIEnv *` 的线程中用 `NewGlobalRef` 创建长期引用，并在合适时点用 `DeleteGlobalRef` 释放。native 线程进入 JVM 前需按 JNI 约定 attach，退出前 detach；但具体封装还应处理 VM 关闭、回调重入和异常路径。

## 用工具把推理变成证据 {#measurement}

一个最小观测流程：

```sh
javac Publication.java
javap -c -v Publication
java -Xlog:class+load=info -Xlog:gc* Publication
java -XX:StartFlightRecording=filename=run.jfr,dumponexit=true Publication
```

- `javap -c -v` 检查 class version、常量池、descriptor、bytecode 和 stack map；
- unified logging 观察类加载、GC、safepoint 或编译相关事件；
- [Java Flight Recorder](https://openjdk.org/jeps/328) 把分配、锁、线程、GC 和 CPU 样本放进同一时间线；
- [JMH](https://openjdk.org/projects/code-tools/jmh/) 处理 JVM benchmark 的 warm-up、dead-code elimination、constant folding 和多 fork 等常见陷阱。

微基准至少要报告 JDK 完整版本、collector、heap flags、warm-up、fork 数、输入分布和机器拓扑。峰值吞吐测试不代表冷启动，平均停顿不代表 tail latency，JIT 编译时间也不应悄悄排除在短命服务之外。

### 常见失效模式

| 症状 | 容易下的错误结论 | 应验证的层 |
| --- | --- | --- |
| 对象很多 | `new` 本身一定慢 | 逃逸、分配率、live-set、GC |
| 一次运行变快 | JIT 已稳定 | compilation log、warm-up、profile |
| `volatile` 存在 | 复合状态已原子 | JMM 边与不变量 |
| 堆未满却 OOM | GC 有 bug | native memory、direct buffer、metaspace、线程 |
| 同名类转换失败 | class 文件不同 | defining loader 与 module layer |
| native 回调偶发崩溃 | Java 异常 | `JNIEnv *`、reference lifetime、ABI |

## 跨层连接 {#connections}

- class file 与 native object file 都是模块间契约，但前者由 JVM 验证和动态解析，后者更多依赖平台 ABI；可对照[编译流水线](../tooling/compiler-pipeline.md)。
- JMM 的 happens-before 与 C/C++ 内存模型共享许多术语，却不能机械映射所有顺序；硬件落地可见[原子操作与内存模型](../architecture/atomics-memory-model.md)。
- GC barrier、对象布局和 cache locality 会共同决定延迟；可结合[缓存与一致性](../architecture/cache-coherence.md)。
- class loader、module、OS process 与 container 是不同隔离层；可结合[隔离与容器](../os/isolation-containers.md)。

Java 性能工作的核心不是寻找一个“最快 JVM 参数”，而是沿源码语义、bytecode、运行时 profile、托管堆和操作系统观测逐层建立证据。

## Reference

- [Java SE 25 and JDK 25 specifications](https://docs.oracle.com/en/java/javase/25/docs/specs/index.html)
- [Java Language Specification, Java SE 25 Edition](https://docs.oracle.com/javase/specs/jls/se25/html/index.html)
- [Java Virtual Machine Specification, Java SE 25 Edition](https://docs.oracle.com/javase/specs/jvms/se25/html/)
- [JVMS Chapter 4 — The class File Format](https://docs.oracle.com/javase/specs/jvms/se25/html/jvms-4.html)
- [JVMS Chapter 5 — Loading, Linking, and Initializing](https://docs.oracle.com/javase/specs/jvms/se25/html/jvms-5.html)
- [JLS Chapter 17 — Threads and Locks](https://docs.oracle.com/javase/specs/jls/se25/html/jls-17.html)
- [JDK 25 Garbage Collection Tuning Guide](https://docs.oracle.com/en/java/javase/25/gctuning/index.html)
- [Java Native Interface Specification, Java SE 25](https://docs.oracle.com/en/java/javase/25/docs/specs/jni/design.html)
- [OpenJDK Java Object Layout project](https://openjdk.org/projects/code-tools/jol/)
- [JEP 328 — Flight Recorder](https://openjdk.org/jeps/328)
- [OpenJDK Java Microbenchmark Harness project](https://openjdk.org/projects/code-tools/jmh/)
