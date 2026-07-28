# 编译器流水线：从语义到机器

编译器不是“把高级代码翻译成汇编”的单一函数。它是一串逐步降低抽象层级、同时保留源语言可观察语义的变换。每一层选择一种更适合当前问题的表示：AST 适合名字与类型，SSA 适合数据流，Machine IR 适合寄存器与指令约束，对象文件适合链接与加载。

## 总览 {#overview}

<figure class="sys-figure" id="compiler-pipeline">
  <a class="sys-figure__media" href="../../assets/figures/compiler-pipeline.svg">
    <img src="../../assets/figures/compiler-pipeline.svg" alt="源文件经过前端、IR、优化与后端生成目标文件，再由链接器、加载器和语言运行时形成运行中进程" width="1400" height="520" loading="lazy">
  </a>
  <figcaption>每一阶段都把上层语义改写为更具体的契约；目标文件并不是终点，链接、加载、运行时初始化与操作系统映射共同决定最终行为。示意图依据 <a href="https://llvm.org/docs/">LLVM 文档</a>与 <a href="https://gitlab.com/x86-psABIs/x86-64-ABI">System V x86-64 psABI</a> 重新绘制。</figcaption>
</figure>

```text
source
  -> lex / parse
  -> AST + name resolution + type checking
  -> high-level IR
  -> canonicalization + optimization
  -> target lowering + instruction selection
  -> register allocation + scheduling
  -> assembly / object
  -> link / load
```

真实编译器会循环、分层或并行这些阶段；JIT 还会把 profile feedback 送回优化层。图的价值在于定位契约，不是规定唯一架构。

## 前端：建立语言事实 {#frontend}

### 词法与语法

lexer 把字符流分成 token，parser 根据 grammar 构造语法结构。表达式：

```text
a + b * c
```

若 grammar 编码了乘法高于加法，AST 近似为：

```text
Add
├── Name(a)
└── Mul
    ├── Name(b)
    └── Name(c)
```

parser 可由 recursive descent、LR/GLR、parser combinator 等实现。方法选择影响错误恢复、增量解析与 grammar 可维护性，但不应改变合法程序的语言语义。

### 名字、类型与约束

semantic analysis 连接 declaration 与 use，处理 scope、overload、generic constraint、implicit conversion、definite initialization 等。一个类型错误常不是“AST 生成失败”，而是 AST 结构合法却无法满足约束。

符号表并非一张全局 map。现代语言有模块、namespace、import、hygiene、associated item 和多阶段宏；名字解析可能需要构建 scope graph 或多轮 fixed point。

前端输出应明确区分：

- 源语言类型与目标机器类型；
- 隐式转换与显式语法；
- 可诊断错误与允许继续的 recovery node；
- 规范保证、未指定行为和未定义行为；
- debug source location 与 macro expansion location。

## IR：选择可证明的中间世界 {#ir}

中间表示不是越低越好。常见分层：

| 层 | 适合表达 |
| --- | --- |
| AST/HIR | 名字、泛型、闭包、模式匹配 |
| typed IR/MIR | 显式控制流、drop、borrow、异常边 |
| SSA IR | def-use、常量传播、公共子表达式、循环 |
| Machine IR | 目标 opcode、寄存器类、calling convention |
| MC/object | 编码、section、symbol、relocation |

把复杂语言特性一次性降到机器码会丢失优化和诊断需要的信息。分层 lowering 把一项复杂证明拆成局部等价变换。

### SSA

Static Single Assignment 要求每个 SSA value 只定义一次；控制流汇合处用 $\phi$ 选择来自不同 predecessor 的值：

```llvm
entry:
  br i1 %cond, label %left, label %right
left:
  %x1 = add i32 %a, 1
  br label %join
right:
  %x2 = sub i32 %a, 1
  br label %join
join:
  %x = phi i32 [ %x1, %left ], [ %x2, %right ]
  ret i32 %x
```

SSA 让 def-use 显式，但内存仍可被多次写。编译器常用 MemorySSA、alias analysis 或 effect system 建模内存依赖。

## 优化：在证明允许的范围内变换 {#optimization}

优化不是“让每条指令更快”，而是改变整个成本：

- canonicalization 让后续 pass 识别统一形态；
- constant folding/propagation 消除已知计算；
- dead-code elimination 删除不可观察结果；
- inlining 暴露跨函数优化，同时增大 code size；
- loop invariant code motion、unrolling、vectorization 改变循环；
- escape analysis 允许栈分配或 allocation elimination；
- devirtualization 把动态调用转成直接调用；
- interprocedural/LTO 跨 translation unit 分析。

每项变换都依赖前提。例如：

```c
int f(int x) {
    return x + 1 > x;
}
```

若源语言规定有符号溢出为 undefined，优化器可在定义良好的执行中把结果视为真；若语言规定 wrap，则必须保留边界行为。优化器不是“擅自改变程序”，而是在语言允许的集合内缩小实现。

### 成本模型不是事实

vectorizer 估算 trip count、指令延迟、吞吐、register pressure 和 remainder cost。目标硬件、profile 与缓存行为会让预测失准。优化 remark 是解释“为何采用/拒绝”的证据，benchmark 才验证实际收益。

## 后端：匹配真实机器约束 {#backend}

### 指令选择

IR 操作要匹配目标 instruction set。`x * 8 + y` 可能用 shift/add、LEA 或 vector instruction；合法化还要处理目标不直接支持的宽度和操作。

SelectionDAG、GlobalISel、tree pattern matching 等方法在“覆盖 IR 图”和“满足目标约束”之间选择。一个源操作可展开成 runtime call，也可合并进 addressing mode。

### 寄存器分配

SSA value 数通常超过物理寄存器。allocator 根据 live range 决定：

- 哪些值共用寄存器；
- 哪些 spill 到栈；
- 调用前后 caller/callee-saved 责任；
- register class、subregister 与 fixed operand。

可把冲突近似成 interference graph coloring；实际 allocator 还处理 coalescing、live-range splitting 和启发式成本。过度 inline/unroll 可能提高 register pressure，反而增加 spill。

### 指令调度

scheduler 在数据依赖、资源和 latency 限制下重排指令，以暴露 instruction-level parallelism，同时不破坏 memory ordering、异常和 debug 语义。目标模型必须描述 pipeline resource，最终效果仍受微架构与运行时 cache miss 影响。

## 异常、协程与 GC 的跨层 lowering {#cross-layer-lowering}

难点往往不在算术：

- exception 要生成 landing pad、unwind table 与 personality 调用；
- coroutine 要把跨 suspend 点状态提升到 frame，并生成 resume/destroy；
- precise GC 需要 stack map、safepoint 与 write barrier；
- closure 要决定 capture layout、逃逸与调用 ABI；
- async stack trace 要从物理栈重建逻辑调用链；
- sanitizer 要在 IR/机器层插入检查并保留定位信息。

这些机制同时影响优化合法性、ABI、调试和运行时，不能只在前端“语法糖展开”后忘记。

## 编译器正确性 {#correctness}

一个 production compiler 的测试面至少包括：

- parser/type checker 的正反例与 diagnostics；
- IR verifier 与每个 pass 的 invariant；
- transformation differential test；
- codegen 对多个 ISA/ABI 的执行测试；
- debug info、unwind、sanitizer 与 LTO 组合；
- randomized/fuzzed source 与 reducer；
- bootstrap 或大规模真实项目。

优化 bug 的最小化流程：

```text
reproduce with exact compiler + flags
  -> remove link/runtime variables
  -> compare -O0 / -O1 / ...
  -> save preprocessed source / IR
  -> bisect pass pipeline
  -> reduce while preserving mismatch
```

不要先假定是编译器 bug。源程序中的 UB、data race、uninitialized read 和 ABI mismatch 更常见；sanitizer 与 IR verification 是前置证据。

## 一组可重复实验 {#experiments}

以 Clang/LLVM 21.1 为例：

```bash
clang -O2 -S -emit-llvm demo.c -o demo.ll
opt -S -passes='default<O2>' demo.ll -o optimized.ll
llc -O2 optimized.ll -o demo.s
clang -O2 -Rpass=.* -Rpass-missed=.* demo.c -c
clang -O2 -fsave-optimization-record demo.c -c
```

记录 `clang --version`、target triple、sysroot、flags 和源 revision。主线 LLVM 文档指向下一开发版，研究固定发布行为时应使用对应 `releases.llvm.org/<version>/` 文档。

## 性能与错误边界 {#performance-failures}

- 编译时间分前端、优化、codegen、link，不能用总时间猜热点；
- runtime 性能同时看 code size、I-cache、branch、vectorization 与 spill；
- `-O3` 不保证比 `-O2` 快，PGO 也会因 profile 偏差伤害冷路径；
- debug build、assert build 与 release build 的编译器行为不同；
- cross compilation 必须同时固定 target triple、CPU/features、ABI、sysroot 与 linker；
- incremental compiler 的缓存 key 若漏掉隐式输入，会得到“快速但错误”的产物。

## 继续阅读

- 深入 SSA、UB 与 pass pipeline：见 [LLVM 与优化](llvm-optimization.md)。
- 从 object 到进程：见[链接、加载、ELF 与 ABI](linking-loading.md)。
- 从 source location 到断点：见[调试、符号与动态分析](debugging.md)。

## Reference

- [Clang 21.1.0: Introduction to the Clang AST](https://releases.llvm.org/21.1.0/tools/clang/docs/IntroductionToTheClangAST.html)
- [LLVM 21.1.0 Language Reference](https://releases.llvm.org/21.1.0/docs/LangRef.html)
- [LLVM 21.1.0 Code Generator](https://releases.llvm.org/21.1.0/docs/CodeGenerator.html)
- [LLVM 21.1.0 New Pass Manager](https://releases.llvm.org/21.1.0/docs/NewPassManager.html)
- [LLVM 21.1.0 Optimization Remarks](https://releases.llvm.org/21.1.0/docs/Remarks.html)
- [LLVM: A Compilation Framework for Lifelong Program Analysis & Transformation](https://llvm.org/pubs/2004-01-30-CGO-LLVM.html)
- [LLVM Documentation](https://llvm.org/docs/)
- [System V x86-64 psABI](https://gitlab.com/x86-psABIs/x86-64-ABI)
- [CompCert: A formally verified optimizing compiler](https://compcert.org/doc/)
