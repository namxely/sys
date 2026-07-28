# 链接、加载、ELF 与 ABI

编译器把一个 translation unit 变成 object file 后，函数地址、全局变量位置和外部引用往往仍未确定。链接器组合 section、解析 symbol、应用或保留 relocation，生成 executable/shared object；程序启动时，内核与动态加载器再把 file segment 映射成进程映像，完成运行时重定位和初始化。

本文以 ELF Object File Format 4.3 draft 与 System V ABI 为格式语义，以 GNU Binutils 2.46 `ld`、Linux/glibc `ld.so` 为具体工具和加载实现实例。Mach-O、PE/COFF、musl、Android linker 与 Windows loader 的规则不同。

## 同一个 ELF 的两种视图 {#sections-segments}

### Section：给链接器看

section header table 描述 `.text`、`.rodata`、`.data`、`.bss`、symbol table、string table、relocation 与 debug sections。它们服务于 link editor、debugger 和分析工具。

### Segment：给加载器看

program header table 描述 `PT_LOAD`、`PT_DYNAMIC`、`PT_INTERP`、`PT_TLS` 等 segment，告诉系统如何创建进程映像。多个 section 可被合并进同一个 segment：

```text
ELF file                            process virtual memory
sections                            segments / mappings
.text ----\                         r-x PT_LOAD
.rodata ---+--> linker script --->  r-- PT_LOAD
.data -----+                        rw- PT_LOAD
.bss ------/                        zero-filled tail
```

section 与 segment 不是同义词。strip 掉某些 section header/debug info 后，程序仍可能依靠 program headers 正常加载。

```bash
readelf -hSW program
readelf -l program
```

分别观察 ELF header/sections 与 program headers，并用 `Section to Segment mapping` 对照。

## Symbol：名字、绑定与可见性 {#symbols}

ELF symbol table entry 记录 name、value、size、type、binding、visibility 和 section index。常见 binding：

- `STB_LOCAL`：object 内局部；
- `STB_GLOBAL`：可参与跨 object 解析；
- `STB_WEAK`：缺失时可保留特殊语义，强定义通常优先。

visibility 进一步控制导出和 interposition：

- default visibility 可进入动态 symbol resolution；
- hidden 不被其他 object preempt，常允许更直接代码生成；
- protected/internal 有平台规定的更窄语义。

语言层 name 与 symbol name 之间还有 mangling。C++ overload、namespace、template 和类型信息需要 ABI 编码；`extern "C"` 主要选择 C linkage/calling convention，并不自动固定 struct layout 或 allocator。

### ODR、COMDAT 与 weak

inline function、template、vtable 可能在多个 object 发射。ELF/ABI 和 linker 通过 COMDAT group、weak/vague linkage 等机制保留一个等价定义。若定义实际上不等价，链接成功也不代表程序定义良好。

## Relocation：把未知地址推迟 {#relocations}

assembler 无法知道外部 symbol 最终地址，于是在 object 中留下 relocation entry。一个典型 relocation 计算包含：

- $S$：symbol value；
- $A$：addend；
- $P$：被修补位置；
- $B$：object load base；
- $G/L$：GOT/PLT 等平台量。

例如某类 PC-relative relocation 具有：

$$
\text{result} = S + A - P
$$

具体公式由 psABI 的 relocation type 定义。链接器把结果写入 instruction/data field，必须同时满足位宽、范围、对齐和 opcode encoding。

```bash
readelf -rW file.o
llvm-objdump -dr file.o
```

`objdump -d` 只看占位 instruction 容易误读；`-r` 把 relocation 与反汇编并列，才知道链接后会引用谁。

### PIC 与 GOT

Position-independent code 避免把绝对地址散落在只读 text：

- 代码用 PC-relative 方式定位 Global Offset Table；
- GOT slot 保存全局数据或函数最终地址；
- load base 改变时，动态加载器集中重定位数据页；
- PIE 让主 executable 也可被 ASLR 放在不同基址。

PIC 不是“没有 relocation”，而是把 relocation 设计成可共享、可重定位的形式。不同 ISA 的 PC-relative addressing 能力不同，成本不能一概而论。

## 静态链接与 archive 搜索 {#static-linking}

`.a` archive 是 object member 集合和索引，不是“已经合成的大 object”。传统 linker 从命令行左到右处理输入，遇到 archive 时抽取能满足当前 undefined symbol 的 member；之后出现的新 undefined 不一定让 linker 回头。

```bash
cc main.o -lconsumer -lprovider
```

若 `consumer` 依赖 `provider`，顺序通常重要。循环依赖可用：

```bash
cc main.o -Wl,--start-group -la -lb -Wl,--end-group
```

但 group 会反复搜索 archive，增加 link cost；更好的模块边界通常能消除循环。

静态链接的收益包括部署依赖减少和部分 whole-program optimization；代价可能包括：

- binary size 与 page cache duplication；
- 安全修复需重新链接/发布；
- NSS、locale、plugin、dlopen 等运行时机制未必真正静态；
- LGPL/其他许可证的分发义务需单独审查；
- kernel ABI 之外仍可能依赖目标系统行为。

## 动态链接：依赖图与符号查找 {#dynamic-linking}

动态 ELF 的 `PT_INTERP` 指向动态加载器。`.dynamic`/`PT_DYNAMIC` 提供 `DT_NEEDED`、string/symbol/hash table、relocation、runpath 等。

启动概念步骤：

1. 内核验证 executable，创建地址空间并映射主程序 segment；
2. 根据 `PT_INTERP` 启动 dynamic linker；
3. 加载器解析依赖并映射 shared objects；
4. 应用 relative、symbol、TLS 等 relocations；
5. 建立初始 TLS，执行必要 initializer；
6. 把控制转给 runtime entry，最终调用 `main`。

Linux/glibc 的精确 library search order受 `DT_RPATH`、`LD_LIBRARY_PATH`、`DT_RUNPATH`、cache、默认目录和 secure-execution mode 影响。`RPATH` 与 `RUNPATH` 的传递语义不同；setuid/capability 等安全执行会忽略或清除一部分环境变量。

```bash
readelf -dW program
ldd program
LD_DEBUG=libs,bindings ./program
```

`ldd` 在不可信 binary 上有历史安全边界；更安全的静态检查可从 `readelf -d` 开始，并在隔离环境验证实际 loader。

### PLT、lazy binding 与 RELRO

函数外部调用常通过 Procedure Linkage Table 与 GOT slot：

```text
call foo@PLT
  -> GOT[foo]
     -> first call: resolver -> lookup foo -> patch slot
     -> later calls: direct target
```

lazy binding 把 lookup 延后到首次调用，缩短部分启动时间，却把延迟放进业务路径并需要可写 GOT slot。`-z now`/`LD_BIND_NOW` 可在启动期完成；RELRO 把完成 relocation 后不应再写的区域设为只读。具体组合以 linker 与 loader 版本核验。

symbol interposition 允许某个 definition preempt 另一个，也限制优化器直接绑定。hidden visibility、`-Bsymbolic`、`-fno-semantic-interposition` 等改变语义或优化边界，库作者必须理解 plugin/override 需求。

## ABI：二进制契约的全表面 {#abi}

API 说“调用哪个函数”；ABI 还规定机器如何调用：

- scalar/aggregate 参数放哪些寄存器或栈；
- stack alignment、red zone、callee/caller-saved；
- return value、variadic、vector type；
- data size/alignment、bit-field 与 enum；
- symbol mangling、visibility、versioning；
- exception/unwind 与 RTTI；
- TLS model；
- object format、relocation 与 dynamic linking；
- language runtime 和标准库二进制接口。

```c
/* stable_abi.h */
#include <stddef.h>
#include <stdint.h>
typedef struct {
    uint32_t abi_version;
    uint32_t size;
    const char *data;
    size_t data_len;
} message_v1;
int process_message(const message_v1 *msg);
```

版本与 size 字段允许调用方/被调用方协商已知前缀；仍需固定 integer width、pointer ownership、string encoding、threading、error 和 allocator。

### C++ ABI

除 platform psABI 外，C++ ABI 还覆盖：

- vtable/vptr 与多重继承 adjustment；
- name mangling；
- RTTI 与 `dynamic_cast`；
- exception object、personality 和 unwind；
- guard variable 与 static initialization；
- template/inline/vtable emission。

更换 compiler major 不一定破坏 ABI，但更换标准库、编译选项、debug iterator、sanitizer、exception/RTTI 模式都可能。跨长期稳定边界常导出窄 C ABI，隐藏 C++ 类型，并在同一 module 内完成分配和释放。

## TLS、初始化与卸载 {#tls-init}

Thread-local storage 通过 `PT_TLS` 和 psABI TLS model 实现。编译器可选 local-exec、initial-exec、local-dynamic、general-dynamic 等模型，在可用范围与访问成本间权衡；`dlopen` 场景限制最激进模型。

global constructor、`.init_array`、language runtime initialization 与 `atexit` 共同形成启动/退出图。跨 translation unit 的初始化顺序可能不稳定；`dlclose` 还会引入：

- 函数指针/对象仍被其他线程使用；
- TLS destructor 指向已卸载 code；
- exception/RTTI 对象跨 module；
- background thread 未停止；
- static destructor 顺序。

plugin 卸载远比 `dlclose(handle)` 一步复杂，许多系统选择进程级隔离或不卸载。

## 工具化检查 {#inspection}

```bash
file program
readelf -hSWlrdVn program
nm -C --defined-only libexample.so
objdump -T libexample.so
ld --verbose
patchelf --print-interpreter program
```

回答问题时匹配工具：

| 问题 | 证据 |
| --- | --- |
| 缺哪个 symbol | `nm`/`readelf -Ws`、link map |
| 谁需要某个库 | `readelf -d` 的 `DT_NEEDED` |
| 地址为何变化 | relocation、PIE/ASLR、load map |
| 运行时加载谁 | loader debug、`/proc/<pid>/maps` |
| ABI 是否变化 | exported symbol/version + layout/calling convention test |
| binary 为何变大 | section size、map file、template/LTO/debug |

## 常见错误 {#failure-modes}

- `undefined reference`：定义未链接、archive 顺序、visibility、mangling 或版本不匹配；
- `multiple definition`：ODR、common/strong symbol、生成文件重复；
- `relocation truncated`：target relocation field 范围不足，需改变 code model/PIC/layout；
- `cannot open shared object`：search path、RUNPATH、架构、secure mode；
- `version 'GLIBCXX_*' not found`：运行时标准库 symbol version 比构建环境旧；
- 启动即崩溃：TLS、constructor、relocation、IFUNC、ABI mismatch；
- 仅 release 崩溃：源 UB、LTO 暴露、visibility/interposition 变化；
- plugin 随机崩溃：allocator、exception、RTTI、线程与卸载生命周期跨边界。

## 继续阅读

- C++ object ABI 的语言侧：见 [C++](../languages/cpp.md#object-model-abi)。
- 链接前的 IR 与 LTO：见 [LLVM 与优化](llvm-optimization.md#lto-pgo)。
- symbol 如何映射回源码：见[调试、符号与动态分析](debugging.md)。

## Reference

- [ELF Object File Format 4.3 draft](https://gabi.xinuos.com/elf/)
- [ELF：Program loading and dynamic linking](https://gabi.xinuos.com/elf/07-loading-intro.html)
- [ELF：Relocation](https://gabi.xinuos.com/elf/06-reloc.html)
- [ELF：Dynamic linking](https://gabi.xinuos.com/elf/08-dynamic.html)
- [System V ABI, Edition 4.1](https://refspecs.linuxfoundation.org/elf/gabi41.pdf)
- [System V AMD64 psABI](https://gitlab.com/x86-psABIs/x86-64-ABI)
- [GNU Binutils 2.46 `ld` manual](https://sourceware.org/binutils/docs/ld/)
- [GNU `ld`：Linker scripts](https://sourceware.org/binutils/docs/ld/Scripts.html)
- [Linux `ld.so(8)`](https://man7.org/linux/man-pages/man8/ld.so.8.html)
- [Itanium C++ ABI](https://itanium-cxx-abi.github.io/cxx-abi/abi.html)
- [Itanium C++ ABI：Exception handling](https://itanium-cxx-abi.github.io/cxx-abi/abi-eh.html)
