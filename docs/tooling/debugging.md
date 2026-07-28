# 调试、符号与动态分析

调试器同时面对两个世界：程序员写的是变量、作用域和调用；机器运行的是地址、寄存器、栈、优化后的指令和异步事件。DWARF 等 debug information 负责映射，但优化会内联、合并、拆分或消除源码实体，因此“变量被优化掉”不是调试器偷懒，而是物理执行中可能不再存在单一存放位置。

本文以 DWARF 5、GDB 17.2 与 LLVM/Clang 21.1 文档为可重现工具基准。命令和 debug format support 会随 debugger、compiler、object format 与平台变化。

## 从症状到证据链 {#evidence-chain}

一个高质量调试会话先固定：

- exact binary 与 build ID；
- source revision、compiler、flags、依赖；
- 输入、环境、配置和随机 seed；
- OS/kernel/architecture；
- crash signal/exception 与时间；
- core dump、日志、trace、profile 的对应 request。

随后按层缩小：

```text
observable failure
  -> first bad state / violated invariant
  -> responsible instruction
  -> source construct and inputs
  -> ownership / ordering / ABI / resource cause
```

栈回溯是起点，不是根因。顶帧常只是最后一次解引用、assert 或 allocator 检测到早先破坏。

## Debug information：映射而非副本 {#debug-information}

DWARF 5 把信息组织为 compilation unit 与 Debugging Information Entry（DIE），并用：

- line table 映射机器地址到 source location；
- location expression/list 描述变量在不同 PC 区间的位置；
- Call Frame Information 描述 stack unwinding；
- type DIE 描述结构与关系；
- range list 描述被拆分或不连续的 code；
- macro、name index、split DWARF 支持更大工程。

变量可能：

```text
PC range A: register rax
PC range B: stack CFA-24
PC range C: value reconstructed from expression
PC range D: unavailable / optimized out
```

所以源码单步在优化 build 中可能跳行、重复停留或直接跨过函数。debugger 只能呈现 compiler 发射且在优化中维护的信息。

### Debug 与优化不是二选一

`-O0 -g` 最易观察，却可能改变 timing、layout、inlining 和 race。生产 crash 更应保留实际 optimization 的 symbol：

```bash
clang++ -O2 -g -fno-omit-frame-pointer app.cc -o app
```

frame pointer 能改善部分 profiler/unwinder，但不是 DWARF unwind 的替代，也有小的寄存器成本。是否启用应按平台与观测栈选择。

## 符号分离、Build ID 与 debuginfod {#symbol-management}

发布 binary 可剥离 debug section，同时把完整符号安全存储：

```bash
objcopy --only-keep-debug app app.debug
strip --strip-debug app
objcopy --add-gnu-debuglink=app.debug app
readelf -n app
```

GNU build ID 可把 deployed binary 与 symbol 精确关联；`.gnu_debuglink` 用 filename/CRC 找同伴。debuginfod 允许 debugger 按 build ID 获取 executable/source/debug info。

安全边界：

- symbol server 可能含 source path、内部类型与源码，应控制访问；
- binary 与 symbol 必须按 build ID 验证，不能仅凭版本字符串；
- strip 后仍保留 dynamic symbol，不能把“无 debug info”当成无公开接口；
- reproducible build 需规范化 debug path，同时保留 debugger source mapping。

## 断点、观察点与单步 {#breakpoints}

### 软件断点

在 x86 上，debugger 常把目标 instruction 首字节临时改成 `INT3`，触发 trap 后恢复原指令、调整 PC 并单步越过。写 text page、self-modifying/JIT code、多线程同时执行会增加复杂性。

### 硬件断点/观察点

CPU debug register 可在地址执行、读写时触发，不必修改 code，但数量、对齐、大小和支持的访问类型有限。软件 watchpoint 可能通过反复单步比较值，开销巨大。

### source step 的真实含义

`next`、`step` 要根据 line table、call、inline info 和临时断点推断下一个源码位置。macro、tail call、inlining 与 optimized-out branch 会让直觉失效。关键时切到：

```gdb
set disassemble-next-line on
layout asm
info registers
x/16gx $sp
disassemble /m function
```

同时看 source 与 instruction，避免对不存在的源码顺序作解释。

## 一次可复用的 GDB 会话 {#gdb-session}

```gdb
set pagination off
set print pretty on
set breakpoint pending on
set disassemble-next-line auto
break main
run
thread apply all bt full
info sharedlibrary
info proc mappings
```

条件断点与 command list 能捕捉第一处坏状态：

```gdb
break update if index >= capacity
commands
  silent
  printf "index=%zu capacity=%zu\n", index, capacity
  bt 6
  continue
end
```

条件可能在 inferior 中求值并显著减速，也会改变 race。更低扰动的 tracepoint、硬件 watchpoint、日志或 record/replay 需按场景选择。

### 多线程

```gdb
info threads
thread apply all bt
set scheduler-locking step
```

停止所有线程会冻结某些 race，但也可能死锁在 debugger 读取需要 inferior 执行的表达式。调用 inferior function、执行 pretty-printer 和持锁求值都可能修改状态；先做只读取证。

## Core dump：从死亡现场开始 {#core-dump}

```bash
ulimit -c unlimited
gdb ./app core
```

基础顺序：

1. `info files` 验证 executable/core；
2. `info sharedlibrary` 和 mappings 验证依赖；
3. 记录 signal、fault address、PC、register；
4. `thread apply all bt full` 看所有线程；
5. 反汇编 PC 周围，确认 faulting instruction；
6. 检查操作数地址属于哪一 mapping、对象生命周期与权限；
7. 从坏指针/状态向上追溯来源。

SIGSEGV 不是“空指针”同义词。可能是：

- unmapped address；
- 写只读 page；
- execute NX page；
- stack overflow/guard page；
- use-after-free 后页被回收；
- ABI mismatch 导致错误 return address；
- data race 撕裂指针；
- memory corruption 很早发生。

core 是进程瞬间快照，不包含此前事件历史。结合 allocator diagnostics、sanitizer、trace 或 record/replay 才能找到“何时写坏”。

## Sanitizer：插桩的运行时证明助手 {#sanitizers}

Clang compiler-rt 提供多类 instrumentation：

| 工具 | 主要发现 | 不能据此证明 |
| --- | --- | --- |
| ASan | 越界、use-after-free/return 等 | 所有未执行路径安全 |
| UBSan | 选定语言 UB | 未启用检查或全部 semantic UB |
| TSan | 已执行路径 data race | 无逻辑 race、死锁 |
| MSan | 未初始化值传播 | 非 instrumented 边界完整 |
| LSan | 检查点上仍未释放且不可达的堆分配，并区分直接与间接泄漏 | 通用资源泄漏、仍可达的长期增长或其根因 |

```bash
clang++ -O1 -g -fno-omit-frame-pointer \
  -fsanitize=address,undefined app.cc -o app-asan
./app-asan
```

ASan 用 shadow memory、redzone、quarantine 等机制改变地址空间、分配时序和 RSS；报告中的 allocation/free stack 很有价值，但 sanitizer build 不是性能基线。TSan 与 ASan 通常不能简单合并，应分别运行。

### 报告的正确读法

1. 从 error class 和 fault address 开始；
2. 找出当前访问的 source location；
3. 找 allocation、free 或前一冲突访问；
4. 识别对象 owner 与跨线程 happens-before；
5. 写最小 regression test；
6. 修不变量，而非只移动触发点；
7. 在无 sanitizer 的实际配置复测功能与性能。

## Record/replay 与时间旅行 {#record-replay}

rr 在受支持 Linux/x86 环境记录进程的非确定输入与调度，随后确定性 replay，支持 reverse-continue/reverse-step。它非常适合：

- 难复现 race；
- 错误很晚暴露，需反向寻找写入；
- 需要反复尝试不同 watchpoint；
- 现场不能多次重跑。

限制包括：

- 支持的平台/CPU/系统调用边界；
- recording 开销和磁盘；
- 不等价于分布式系统全局 replay；
- GPU、设备、共享内存和外部进程可能受限；
- 记录环境中的行为仍可能不同于生产。

```bash
rr record ./app input
rr replay
```

调试器的 `record full`、process record、VM snapshot 或应用级 deterministic log 各覆盖不同层；选择前先列出所有非确定输入。

## JIT、GC 与异步栈 {#managed-runtimes}

JIT code 没有固定在静态 object 中，runtime 需通过 debugger JIT interface、perf map/jitdump 或专用 inspector 注册 code range 和 symbol。代码优化/失效后地址映射会变化。

GC 移动物件需要 runtime 维护 handle/heap inspection；仅看裸地址可能过时。async/continuation 还把逻辑调用链拆散到多个物理栈帧，语言 runtime 必须保留 async parent 才能还原。

因此“GDB 看不到变量”可能是：

- code 已 JIT/deopt；
- object 已移动；
- coroutine 已挂起，状态在 heap frame；
- optimized stack 没有完整 unwind；
- native/managed 边界缺少桥接 symbol。

需要把语言 inspector、native debugger 与 runtime trace 结合。

## 调试策略：停、看、量 {#strategy}

| 目标 | 首选手段 | 代价 |
| --- | --- | --- |
| 确定崩溃现场 | core + symbols | 缺历史 |
| 捕捉第一处状态变化 | watchpoint/breakpoint | 扰动调度 |
| 内存安全 | ASan/MSan/UBSan | 高开销、改变布局 |
| data race | TSan/专用 race detector | 更高开销、覆盖依赖输入 |
| 不可复现执行 | record/replay | 平台和外部世界限制 |
| 生产低扰动 | sampling/eBPF/tracepoint | 细节与精确时序有限 |
| 业务因果链 | structured trace/log | 需预先埋点和采样策略 |

动态工具可组合，但不要同时开启所有机制后假定结果仍代表原始时序。每次实验只改变一个主要观测手段，并记录其开销。

## 常见失败 {#failure-modes}

- symbols 与 binary 不匹配，回溯“像真的”却完全错；
- 只看 crashing thread，忽略持锁/写坏内存的其他线程；
- 在 debugger 中调用函数改变状态；
- 只修最后一次越界，而不修长度/所有权协议；
- debug build 不复现便断言“优化器 bug”；
- sanitizer 无报告便断言没有 UB/race；
- optimized variable 不可见便用错误猜值；
- 把 wall-clock timestamp 当分布式全序；
- 上传含私有源码路径/数据的 core 或 symbol。

## 继续阅读

- debug info 如何穿过优化：见 [LLVM 与优化](llvm-optimization.md)。
- binary mapping 与 symbol：见[链接、加载、ELF 与 ABI](linking-loading.md)。
- 不停进程的采样与追踪：见[采样、perf 与 eBPF](../performance/profiling.md)。

## Reference

- [DWARF Version 5 Standard](https://dwarfstd.org/dwarf5std.html)
- [GDB 17.2 Manual](https://sourceware.org/gdb/download/onlinedocs/)
- [GDB：Debugging optimized code](https://sourceware.org/gdb/current/onlinedocs/gdb/Optimized-Code.html)
- [GDB：Process record and replay](https://sourceware.org/gdb/current/onlinedocs/gdb/Process-Record-and-Replay.html)
- [LLVM 21.1.0：Source Level Debugging](https://releases.llvm.org/21.1.0/docs/SourceLevelDebugging.html)
- [LLDB Documentation](https://lldb.llvm.org/)
- [Clang 21.1.0 AddressSanitizer](https://releases.llvm.org/21.1.0/tools/clang/docs/AddressSanitizer.html)
- [Clang 21.1.0 ThreadSanitizer](https://releases.llvm.org/21.1.0/tools/clang/docs/ThreadSanitizer.html)
- [Clang 21.1.0 UndefinedBehaviorSanitizer](https://releases.llvm.org/21.1.0/tools/clang/docs/UndefinedBehaviorSanitizer.html)
- [rr Project Documentation](https://rr-project.org/)
- [elfutils debuginfod](https://sourceware.org/elfutils/Debuginfod.html)
