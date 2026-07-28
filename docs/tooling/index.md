# 编译与工具链

工具链把语言承诺翻译为可加载、可调试、可复现的机器产物。任何一段“编译成功”的程序，都隐含了前端语义、IR、目标 ISA、ABI、对象格式、链接器、动态加载器、标准库与构建环境之间的一整组协议。

## 阅读地图

- [编译器流水线](compiler-pipeline.md)：从 token、AST 和类型检查走到指令选择、寄存器分配与调度。
- [LLVM 与优化](llvm-optimization.md)：理解 SSA、poison、pass pipeline、LTO、PGO 和 optimization remarks。
- [链接、加载、ELF 与 ABI](linking-loading.md)：追踪 section、symbol、relocation、segment、PLT/GOT 与进程入口。
- [构建系统与可复现产物](build-reproducibility.md)：把依赖图、增量构建、hermeticity 与字节级重现连起来。
- [调试、符号与动态分析](debugging.md)：从 DWARF、断点和 core dump 到 sanitizer、record/replay。

## 一条最短实验链

面对一段 C/C++ 程序，可以按层取证：

```bash
clang++ -std=c++23 -E app.cc > app.ii
clang++ -std=c++23 -Xclang -ast-dump -fsyntax-only app.cc
clang++ -std=c++23 -S -emit-llvm app.cc -o app.ll
clang++ -std=c++23 -c app.cc -o app.o
llvm-objdump -dr --source app.o
clang++ app.o -Wl,-Map=app.map -o app
readelf -hSWlrsd app
```

每一步回答不同问题：预处理输入、语义树、优化 IR、可重定位对象、机器指令、链接决策与运行时依赖。不要让单一反汇编承担全部解释。

## 边界

这里关注通用编译、链接、构建与调试机制。具体语言对象模型回到[语言与运行时](../languages/index.md)；测量工具的实验设计与生产观测进入[性能与可观测性](../performance/index.md)。

## Reference

- [LLVM 21.1.0 Documentation](https://releases.llvm.org/21.1.0/docs/)
- [Clang 21.1.0 Documentation](https://releases.llvm.org/21.1.0/tools/clang/docs/)
- [ELF Object File Format](https://gabi.xinuos.com/elf/)
- [GNU Binutils Documentation](https://sourceware.org/binutils/docs/)
- [DWARF Version 5 Standard](https://dwarfstd.org/dwarf5std.html)
- [GNU GDB Documentation](https://sourceware.org/gdb/current/onlinedocs/gdb)
