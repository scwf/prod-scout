# Daft 由入门到进阶实战手册

Daft 是一个专为 AI 和多模态工作负载设计的高性能分布式 DataFrame library。它采用 Rust 编写核心引擎，并提供 Python API，旨在解决传统 DataFrame（如 Pandas、Spark）在处理图像、音频、视频及大模型推理时的痛点。

---

## 目录
1. [快速开始](#1-快速开始)
2. [核心概念：延迟执行与多模态](#2-核心概念)
3. [数据接入与写出](#3-数据接入与写出)
4. [DataFrame 核心算子 (Operations)](#4-dataframe-核心算子)
5. [多模态数据处理](#5-多模态数据处理)
6. [原生 AI 函数：Prompt、Embedding、分类](#6-原生-ai-函数)
7. [进阶：自定义 Python 代码 (UDF)](#7-进阶自定义-python-代码)
8. [性能优化与单机并行](#8-性能优化与单机并行)
9. [大规模扩展：分布式执行与优化](#9-大规模扩展分布式执行与优化)

---

## 1. 快速开始

### 安装
Daft 提供了多种可选依赖，根据需求选择：
```bash
pip install -U "daft[openai]"  # 包含 AI 功能
# 或者安装全部功能
pip install -U "daft[all]"
```

### 10分钟上手示例
```python
import daft
from daft import col

# 1. 加载数据 (以 Hugging Face 为例)
df = daft.read_huggingface("calmgoose/amazon-product-data-2020")

# 2. 数据转换 (过滤与选择)
df = df.select("Product Name", "Image").limit(5)

# 3. 多模态操作：下载并解码图像
df = df.with_column("image_bytes", col("Image").regexp_extract(r"^([^|]+)", 1).download())
df = df.with_column("image", col("image_bytes").decode_image())

# 4. 预览结果 (Jupyter 中可直接显示图片)
df.show()
```

---

## 2. 核心概念

### 延迟执行 (Lazy Evaluation)
Daft 默认不会立即执行计算。当你调用 `read_parquet` 或 `with_column` 时，它只是在构建查询计划。
- **`.show(n)`**: 触发计算并显示前 n 行（用于调试）。
- **`.collect()`**: 触发计算并将结果全部加载到内存。
- **`.write_parquet()`**: 触发计算并将结果流式写入磁盘。

### 多模态意识 (Multimodal Aware)
Daft 将图像、张量、Embedding 视为一等公民，而不是二进制大对象（BLOB）。这意味着你可以直接在列上调用 `.resize()`、`.crop()` 或 `.embed_text()`。

---

## 3. 数据接入与写出

Daft 支持连接几乎所有现代数据源：

| 类型 | 读取函数 | 写入函数 |
| :--- | :--- | :--- |
| **文件** | `read_parquet`, `read_csv`, `read_json` | `write_parquet`, `write_csv` |
| **云存储** | 支持 `s3://`, `gs://`, `az://`, `hf://` | 同上 |
| **表格格式** | `read_iceberg`, `read_deltalake`, `read_hudi`, `read_lance` | `write_iceberg`, `write_deltalake`, `write_lance` |
| **数据库** | `read_sql` (支持 20+ 方言) | 计划中 |

---

## 4. DataFrame 核心算子 (Operations)

Daft 的算子设计兼顾了 Pandas 的易用性和 SQL 的严谨性。

### 选择与投影 (Projection)
- **`select(*cols)`**: 选择指定列，支持表达式。
- **`with_column(name, expr)`**: 添加新列或覆盖现有列。
- **`exclude(*names)`**: 排除指定列。
- **`rename(mapping)`**: 重命名列。

### 过滤与排序 (Selection & Sorting)
- **`where(expr)` / `filter(expr)`**: 根据条件过滤行。
- **`sort(cols, desc=False)`**: 对数据进行全局排序。
- **`limit(n)`**: 限制返回行数。

### 聚合与分组 (Aggregation)
- **`groupby(*cols)`**: 分组算子，返回 `GroupedDataFrame`。
- **`agg([exprs])`**: 配合分组使用，支持 `sum`, `mean`, `min`, `max`, `count`, `list`, `concat` 等聚合。

---

## 5. 多模态数据处理

### 图像处理
```python
from daft import col

df = df.with_column("resized_img", col("image").resize(224, 224))
df = df.with_column("grayscale", col("resized_img").convert_image("L"))
```

### 音频处理
通过 `daft.File` 类型处理音频流：
```python
from daft.functions import file

df = df.with_column("audio", file(col("audio_path")))
# 配合 UDF 使用 soundfile 库进行读取
```

---

## 6. 原生 AI 函数

Daft 内置了与主流 AI 提供商（OpenAI, Google, Transformers）的集成。

### 文本/图像向量化 (Embedding)
```python
from daft.functions.ai import embed_text

df = df.with_column("embedding", embed_text(col("description"), model="text-embedding-3-small", provider="openai"))
```

---

## 7. 进阶：自定义 Python 代码 (UDF)

### 无状态 UDF (`@daft.func`)
适用于简单的逐行或批处理转换。
```python
@daft.func
def add_one(x: int) -> int:
    return x + 1

df = df.with_column("y", add_one(col("x")))
```

### 有状态 UDF (`@daft.cls`)
适用于需要昂贵初始化（如加载模型、数据库连接）的场景。
```python
@daft.cls(gpus=1) 
class MyModel:
    def __init__(self):
        self.model = load_large_model() 

    def __call__(self, batch):
        return self.model.predict(batch)
```

---

## 8. 性能优化与单机并行

Daft 默认使用基于 Rust 的 **Native Runner (Swordfish)**，它会自动利用单机的所有 CPU 核心。

### 配置单机并行度
虽然 Daft 会自动检测 CPU 核心数，但在某些场景下你可能需要手动干预：

- **强制使用本地 Runner**:
  ```python
  import daft
  daft.set_runner_native() # 默认即为此设置
  ```

- **控制下载并发**:
  在处理 URL 下载时，可以通过 `max_connections` 避免触发反爬虫或内存溢出：
  ```python
  df = df.with_column("data", col("url").download(max_connections=32))
  ```

### UDF 并发控制
对于自定义 Python 代码，Daft 提供了精细的并发控制：

- **多线程/进程并发**:
  通过 `concurrency` 参数控制同时运行的 UDF 实例数量。
  ```python
  @daft.func(concurrency=8) # 同时启动 8 个并发任务
  def heavy_task(x):
      ...
  ```

- **绕过 GIL (Global Interpreter Lock)**:
  对于 CPU 密集型的 Python 代码，建议开启进程模式以获得真正的多核并行：
  ```python
  @daft.func(use_process=True) # 在独立进程中运行 UDF
  def cpu_bound_task(x):
      ...
  ```

### 内存与批次管理
- **`into_batches(n)`**: 手动指定批次大小。这对于处理大型图像或视频非常有用，可以防止单次处理数据量过大导致 OOM。
  ```python
  df = df.into_batches(100).with_column("embedding", my_gpu_udf(col("image")))
  ```

---

## 9. 大规模扩展：分布式执行与优化

### 切换运行后端 (Ray)
只需一行代码即可扩展到分布式集群：
```python
# 连接到本地或远程 Ray 集群
daft.set_runner_ray(address="ray://<head-node-ip>:10001") 
```

### 分区管理
- **`repartition(n)`**: 调整数据分区数。在分布式环境下，通常将分区数设置为 Worker 核心数的 2-4 倍以平衡负载。

### 观测性
Daft 在终端执行时会显示实时进度条，包括：
- 每秒处理行数 (rows/s)
- 内存消耗
- 计算预计剩余时间

---

## 总结
Daft 的学习路径建议：
1. **入门**: 掌握 `read_*` 和 `show()`，练习 `col` 核心算子。
2. **进阶**: 掌握单机并行配置，尝试 `download()` 和 `decode_image()` 处理非结构化数据。
3. **专家**: 结合 `@daft.cls` 和 Ray 集群，构建 PB 级生产 AI 流水线。

更多资源请访问 [Daft 官方文档](https://docs.daft.ai)。
