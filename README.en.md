# Computer Systems Knowledge Base — English Companion & Labs

[![Upstream: WineChord/sys](https://img.shields.io/badge/Upstream-WineChord%2Fsys-blue)](https://github.com/WineChord/sys)
[![License: MIT](https://img.shields.io/badge/License-MIT-5c6bc0.svg)](LICENSE)
[![Labs CI](https://github.com/namxely/sys/actions/workflows/labs-ci.yml/badge.svg)](https://github.com/namxely/sys/actions/workflows/labs-ci.yml)

> **Attribution:** This repository is an official fork of [**WineChord/sys**](https://github.com/WineChord/sys) under the [MIT License](LICENSE). All upstream knowledge base chapters in [`docs/`](docs/) remain preserved; this companion guide and [`labs/`](labs/README.md) add bilingual study roadmaps and runnable Python 3.12 systems labs by [@namxely](https://github.com/namxely).

[中文原版 README](README.md) · [Hướng dẫn Tiếng Việt](README.vi.md) · [Labs Documentation](labs/README.md)

---

## Knowledge Map (`docs/`)

| Layer | Module | Focus Areas |
| :--- | :--- | :--- |
| **Foundations & Hardware** | [`foundations/`](docs/foundations/index.md) | Data representation, performance models, memory hierarchy |
| | [`architecture/`](docs/architecture/index.md) | ISA, pipelines, CPU, GPU SIMT, cache coherence, virtual memory & TLB |
| **OS & Concurrency** | [`os/`](docs/os/index.md) | Processes, threads, scheduling, filesystems, async & I/O |
| | [`concurrency/`](docs/concurrency/index.md) | Mutexes, atomics, lock-free structures, coroutines |
| **Networking & Storage** | [`network/`](docs/network/index.md) | Packets, routing, TCP congestion control, DNS, HTTP, TLS, Sockets, RDMA |
| | [`storage/`](docs/storage/index.md) | SSD internals, filesystems, database storage engines & crash consistency |
| **Parallel & Distributed** | [`parallel/`](docs/parallel/index.md) | Parallel patterns, SIMD, synchronization & scaling |
| | [`distributed/`](docs/distributed/index.md) | Consensus (Raft), replication, sharding & fault tolerance |
| **Runtimes & Performance** | [`languages/`](docs/languages/index.md) | C, C++, Go, Rust, Python, JVM, Node.js & Wasm runtimes |
| | [`performance/`](docs/performance/index.md) | Benchmarking, CPU/memory profiling & capacity modeling |
| | [`tooling/`](docs/tooling/index.md) | Compilers, linkers, debuggers & observability tools |
| | [`guide/`](docs/guide/index.md) | Navigation & methodology |

---

## Recommended Study Track (Backend, Systems & Redis-Like Engines)

1. **Memory Hierarchy & Caching**: `docs/architecture/cache-coherence.md` + `docs/storage/` → run `python labs/cache_policies.py`.
2. **Networking, Framing & Wire Protocols**: `docs/network/` + `docs/os/` → run `python labs/resp_protocol.py`.
3. **Distributed Consensus & Go/Python Runtimes**: `docs/distributed/` + `docs/languages/`.

---

## Quick Start (`labs/`)

Requires **Python 3.12+** (zero external packages):

```bash
python -m unittest discover -s labs -v
python labs/cache_policies.py
python labs/resp_protocol.py
```
