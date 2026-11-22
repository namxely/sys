> **Fork Attribution & Extensions** — Official MIT-licensed fork of [`WineChord/sys`](https://github.com/WineChord/sys) (original `LICENSE` & `docs/` preserved).
> Added by `@namxely`: [**English Guide**](README.en.md) · [**Hướng dẫn Tiếng Việt**](README.vi.md) · [**Runnable Cache & RESP2 Systems Labs (`labs/`)**](labs/README.md) [![Labs CI](https://github.com/namxely/sys/actions/workflows/labs-ci.yml/badge.svg)](https://github.com/namxely/sys/actions/workflows/labs-ci.yml)

---

# Sys

一份从程序行为贯穿到硬件与分布式系统的计算机系统知识库。

**在线阅读：[www.wineandchord.com/sys](https://www.wineandchord.com/sys/)**

[![Deploy site](https://github.com/WineChord/sys/actions/workflows/pages.yml/badge.svg)](https://github.com/WineChord/sys/actions/workflows/pages.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-5c6bc0.svg)](LICENSE)

## 内容

- 从数据表示、性能模型与内存层次进入 ISA、微架构、CPU、GPU 和缓存一致性。
- 连接进程、线程、调度、虚拟内存、文件系统、I/O、协程、异步与无锁并发。
- 沿分组、路由、传输、拥塞控制、DNS、HTTP、TLS、Socket 和 RDMA 梳理网络路径。
- 覆盖存储设备、SSD、文件系统、数据库存储、崩溃一致性、并行计算与分布式系统。
- 从语言规范下探到 C、C++、Java/JVM、Go、Rust、Python、JavaScript、TypeScript、Node.js 与 WebAssembly 的运行时行为。
- 以编译、链接、加载、调试、基准、剖析、追踪和容量分析闭合“解释—实现—测量”链路。

## 本地预览

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
npm ci
python scripts/check_copywriting.py
python scripts/check_content.py
python scripts/check_architecture.py
python scripts/check_figures.py
python scripts/check_code.py
python scripts/check_rendering.py
mkdocs build --strict
python scripts/check_links.py --site-dir site
python scripts/check_rendering.py --site-dir site --browser
mkdocs serve
```

浏览器打开 `http://127.0.0.1:8000/sys/`。

## 目录

- `docs/`：网站正文
- `mkdocs.yml`：站点与导航
- `scripts/`：内容、代码、链接与渲染检查
- `.github/workflows/pages.yml`：GitHub Pages 发布流程

## License

正文、原创示意图与自有站点代码采用 [MIT](LICENSE)。第三方依赖保留各自许可证；本地 MathJax 运行时采用其 [Apache License 2.0](docs/assets/vendor/mathjax/LICENSE)。
