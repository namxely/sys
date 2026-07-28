# ISA 与微架构

指令集体系结构（ISA）是软件与处理器之间的长期契约；微架构是实现这份契约的一种内部组织。把两者分开，是理解处理器可移植性、性能和演化的第一步。

## ISA 承诺什么

一个完整 ISA 通常定义：

- 指令编码、寄存器和数据类型；
- 地址计算、load/store 与对齐行为；
- 控制流、异常和中断的架构语义；
- 特权级、页表格式与系统寄存器；
- 原子操作与内存排序；
- 可选扩展及其发现方法。

ISA 一般不承诺 cache 大小、流水线级数、执行端口、分支预测器、实际指令延迟或内部微操作数量。RISC-V 非特权规范甚至明确避免依赖 cache line 大小等微架构特征。

## 同一 ISA，多种机器

x86-64 二进制可以运行在不同代际的 Intel、AMD 处理器上；每款处理器可有不同解码器、乱序窗口、缓存和预测器。类似地，RV64GC 描述一组扩展组合，不限定是五级顺序流水线还是宽发射乱序核心。

这带来两个结果：

1. **正确性按 ISA 判断**：只要程序遵守 ISA/ABI，内部实现可以变化。
2. **性能按具体微架构判断**：指令条数相同，周期数仍可相差很大。

微架构也可能通过微码更新修正内部实现，而不改变应用看到的指令编码。

## ISA 设计空间

### 固定与变长编码

固定长度编码便于并行取指和解码，代码密度可能较低；变长编码提高密度，却让边界识别和宽解码更复杂。RISC-V 基础指令通常为 32 位，并可通过压缩扩展加入 16 位编码；x86 指令则由前缀、opcode、寻址字段和立即数构成可变长度序列。

### 寄存器—寄存器与复杂内存操作

load/store ISA 通常要求算术操作数来自寄存器，内存通过显式 load/store 访问。x86 允许许多指令直接使用一个内存操作数。内部实现仍可能把复杂指令译成多个微操作，因此“CISC 一定直接在硬件执行，RISC 一条指令只做一步”都过于粗糙。

### 扩展与兼容

软件不能仅凭编译目标假设运行机器具有所有扩展。x86 常用 CPUID，Linux 可经 `getauxval(AT_HWCAP)` 暴露 Arm/RISC-V 能力。分发二进制可采用：

- 保守基线；
- 多版本函数与运行时分派；
- 安装时或首次运行时生成；
- 明确要求某一 ISA profile。

## ABI 把 ISA 变成可链接平台

ISA 说明指令，ABI 还规定：

- 参数和返回值放在哪些寄存器或栈位置；
- 哪些寄存器由调用者或被调用者保存；
- 栈对齐、红区和展开信息；
- 数据类型大小、结构体布局与符号约定；
- 系统调用边界和目标文件格式。

下面是一个纯函数及其典型编译观察流程：

```cpp
#include <cstdint>
extern "C" std::uint64_t mix(std::uint64_t x, std::uint64_t y) {
    x ^= y + 0x9e3779b97f4a7c15ULL + (x << 6) + (x >> 2);
    return x;
}
```

```bash
c++ -O3 -std=c++20 -c mix.cpp -o mix.o
objdump -drwC mix.o
readelf -h -A mix.o
```

输出只对当前编译器、参数、目标 triple 与 ABI 成立。指令序列说明编译器选择，不等同于硬件执行时间。

## 从架构指令到微操作

现代处理器前端可能把一条架构指令解码成一个或多个内部微操作（µop）。若常见指令模式已在 µop cache 中，处理器甚至可绕过部分解码路径。随后：

1. 寄存器重命名消除 WAR/WAW 假依赖；
2. µop 进入调度窗口；
3. 操作数就绪且执行端口可用时发射；
4. 结果先写物理寄存器或缓冲；
5. 指令按程序顺序提交，恢复精确异常。

内部 µop 不是 ISA，软件不能依赖其数量或形式。分析工具给出的 µop、端口和延迟也必须匹配具体 CPU 型号。

## 精确异常与推测

乱序执行允许年轻指令先完成，但架构状态通常按顺序提交。若一条较老指令发生 fault：

- 更年轻且尚未提交的结果被丢弃；
- 保存的架构状态指向 fault 边界；
- 内核处理异常，可能修复映射后重试，也可能向进程发信号。

这就是“内部乱序、外部像顺序提交”的关键。推测执行可以留下 cache 等微架构痕迹，却不得把未提交结果直接变成架构状态；这种边界也是推测执行侧信道产生的根源之一。

## 特权级与系统接口

用户态不能直接修改页表、屏蔽中断或访问任意设备。系统调用通过受控入口切换到内核执行；异常由当前指令触发，中断通常来自外部或定时器。三者都改变控制流，但来源、同步性和返回语义不同。

| 事件 | 来源 | 与当前指令关系 | 例子 |
| --- | --- | --- | --- |
| trap / exception | CPU 检测 | 同步 | page fault、非法指令 |
| system call | 程序主动请求 | 同步 | `read`、`mmap` |
| interrupt | 外部设备或定时器 | 通常异步 | 网卡完成、时钟 |

具体术语在不同 ISA 文档中不完全一致，应以目标架构规范为准。

## 怎样验证 ISA 边界

### 静态检查

- `readelf -h -A` 或 `llvm-readobj` 查看目标架构和属性；
- `objdump` 或 `llvm-objdump` 查看实际指令；
- 编译器 `-march`、`-mcpu`、`-mtune` 分别控制可用指令与调优假设；
- ABI 文档确认调用约定，而不是从一次反汇编归纳规则。

### 动态检查

- Linux `/proc/cpuinfo` 适合人工观察，不是最稳定的程序接口；
- x86 使用 CPUID 并同时检查 OS 是否保存扩展状态；
- Linux 程序可使用 `getauxval` 读取 HWCAP；
- 在 QEMU 或模拟器中验证功能时，不能把模拟时延当硬件性能。

## 常见失败模式

- 在不支持的机器上执行可选扩展，触发非法指令；
- 只检查 CPU 能力，没检查操作系统是否启用扩展状态；
- 依赖未文档化微架构行为保证正确性；
- 混用目标文件 ABI、调用约定或浮点 ABI；
- 把 compiler barrier、ISA fence 与 cache flush 当成同一件事；
- 从一条指令名称推断它“原子”或“只需一个周期”；
- 把微码、固件与 ISA 版本混成一个版本号。

## 跨层连接

- 解码、重命名和提交细节进入 [流水线与 ILP](pipeline-ilp-branch.md)；
- load/store 的实际成本由 [缓存一致性](cache-coherence.md) 和 [TLB](virtual-memory-tlb.md) 决定；
- ISA 原子和 fence 只是 [语言内存模型](atomics-memory-model.md) 的实现工具；
- 特权 ISA 为 [进程](../os/process-thread.md)、[调度](../os/scheduling.md) 与 [虚拟内存](../os/virtual-memory.md) 提供机制。

## Reference

- [RISC-V Unprivileged ISA Specification](https://docs.riscv.org/reference/isa/unpriv/unpriv-index.html)
- [RISC-V Privileged Architecture Specification](https://docs.riscv.org/reference/isa/priv/priv-index.html)
- [Intel 64 and IA-32 Architectures Software Developer Manuals](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html)
- [Arm Architecture Reference Manual for A-profile](https://developer.arm.com/documentation/ddi0487/latest/)
- [System V Application Binary Interface AMD64 Supplement](https://gitlab.com/x86-psABIs/x86-64-ABI)
- [RISC-V ELF psABI Specification](https://riscv-non-isa.github.io/riscv-elf-psabi-doc/)
- [Linux getauxval(3)](https://www.man7.org/linux/man-pages/man3/getauxval.3.html)
