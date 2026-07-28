# 语言与运行时

程序设计语言不是孤立的语法集合，而是一组贯穿编译、执行、内存、并发与互操作边界的契约。同一句“创建对象”在 C++ 中可能意味着存储、生命周期与析构责任，在 Go 中会触发逃逸分析和垃圾回收压力，在 Rust 中会改变所有权，在 Python 与 JavaScript 中则落入动态对象模型和具体解释器的实现策略。

## 阅读地图

- [比较语言，而不是比较语法](comparison.md)：用语义、运行时、并发、ABI 与故障模型建立共同坐标。
- [C：抽象机、对象与系统边界](c.md)：从对象表示、未定义行为和原子序走到 ABI 与系统调用。
- [C++：对象、生命周期与内存模型](cpp.md)：从 RAII 一直追到对象布局、异常展开和原子序。
- [Java 与 JVM](java-jvm.md)：把 class file、类加载、JIT、GC、JMM 与 JNI 连成一条运行时路径。
- [Go：goroutine、调度器与垃圾回收](go.md)：理解 G–M–P、channel、`context` 和 GC 成本。
- [Rust：所有权、安全边界与 Future](rust.md)：从借用规则走到 `unsafe` 证明义务与异步状态机。
- [Python：对象模型、CPython 与 asyncio](python.md)：区分语言语义、字节码实现、GIL 与协作式调度。
- [JavaScript：ECMAScript 与宿主事件循环](javascript.md)：拆开语言 Job、HTML task/microtask 与异步组合。
- [TypeScript：结构化类型与类型擦除](typescript.md)：理解静态近似、条件类型、模块解析与运行时边界。
- [Node.js：libuv、流与背压](nodejs.md)：把 JavaScript 回调追到事件循环、线程池、内核 I/O 与资源上限。
- [WebAssembly：验证、线性内存与宿主能力](webassembly.md)：区分 core module、instance、WASI、Component Model 与宿主权限。

## 一条贯穿各页的主线

阅读任何语言特性时，依次追问：

1. **规范保证什么**：哪些行为可移植，哪些未指定，哪些属于未定义行为？
2. **值怎样表示**：对象是内联数据、指针、句柄，还是带标签的动态值？
3. **资源何时释放**：词法作用域、引用计数、追踪式 GC，还是显式关闭？
4. **并发如何建立顺序**：线程、协程、消息、原子操作和取消分别提供什么保证？
5. **实现怎样兑现契约**：编译器、解释器、JIT、运行时与操作系统各承担哪一段？
6. **成本怎样观测**：分配、暂停、上下文切换、缓存失效、系统调用和队列等待如何测量？

这套顺序把“会写代码”推进到“能解释代码为什么正确、为何变慢，以及换一个实现后哪些结论仍成立”。

## 边界

这里讨论可跨应用复用的语言语义与运行时机制。编译、链接和调试进入[编译与工具链](../tooling/index.md)，测量方法进入[性能与可观测性](../performance/index.md)；面向某个特定业务框架的 API 清单不在此处展开。

## Reference

- [ISO/IEC 9899:2024 — C](https://www.iso.org/standard/82075.html)
- [ISO/IEC JTC1/SC22/WG21: C++ working draft](https://eel.is/c++draft/)
- [Java SE 25 Specifications](https://docs.oracle.com/en/java/javase/25/docs/specs/index.html)
- [The Go Programming Language Specification](https://go.dev/ref/spec)
- [The Rust Reference](https://doc.rust-lang.org/reference/)
- [Python Language Reference](https://docs.python.org/3/reference/)
- [ECMAScript Language Specification](https://tc39.es/ecma262/)
- [TypeScript Documentation](https://www.typescriptlang.org/docs/)
- [Node.js API Documentation](https://nodejs.org/api/)
- [WebAssembly Core Specification](https://webassembly.github.io/spec/core/)
