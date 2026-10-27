# S1 文档解析依赖选择记录

## 结论

首期固定使用 `python-docx 1.2.0`、`markdown-it-py 4.2.0`、`pypdf 6.10.0` 和 `jsonschema 4.26.0`。运行依赖写入 `pyproject.toml`，解析与测试环境由 `uv.lock` 锁定。`reportlab 4.4.10` 只用于生成测试 PDF，不进入生产解析路径。

选择原则是：许可证宽松、Python 3.11 可用、Windows/Linux 可安装、中文文本层实测可保真，并允许我们自己控制统一 Document IR。没有使用通用文档框架替代领域契约。

## 候选与选择依据

| 用途 | 选择 | 版本 | 许可证证据 | 实测结论 |
| --- | --- | ---: | --- | --- |
| DOCX | `python-docx` + `lxml` | 1.2.0 / 6.1.3 | wheel 元数据与许可证文件：MIT / BSD-3-Clause | 中文段落、表格单元格、显式分页通过；OOXML 对象需要自行枚举 |
| Markdown | `markdown-it-py` | 4.2.0 | wheel 中两个 LICENSE 文件均为 MIT 文本；元数据未填许可证字段 | 中文、多级标题、列表、表格、代码块、行范围通过 |
| PDF | `pypdf` | 6.10.0 | wheel `License-Expression: BSD-3-Clause` | 两页中文、文本矩阵和页码通过；不承诺视觉表格和多栏阅读顺序 |
| PDF 备选 | PyMuPDF | 未安装、未实测 | 候选涉及 AGPL/商业授权选择，未在本轮引入 | 当前 `pypdf` 已满足文本层 MVP，故不增加授权和部署复杂度 |
| JSON Schema | `jsonschema` | 4.26.0 | wheel `License-Expression: MIT` | Draft 2020-12 Schema 校验通过 |
| 测试样本生成 | `reportlab` | 4.4.10 | wheel 许可证字段为 BSD license | 仅开发依赖，能稳定生成中文双页 PDF |

## 实测环境

### Windows

- Windows 10 `10.0.19045`，CPython 3.14.3，独立 `.venv`。
- 六类依赖安装成功；中文段落、表格、分页和 PDF 坐标断言全部通过。
- `python-docx`、`pypdf`、`markdown-it-py`、`jsonschema`、`reportlab` 是纯 Python wheel；`lxml` 使用 `cp314-win_amd64` wheel。
- 证据：`artifacts/requirement-analysis/dependency-spike/result.json`。

### Linux

- Docker/WSL2 中的 Debian trixie slim，CPython 3.11.17，glibc 2.41。
- 从锁定的同版本范围安装成功；中文小样断言全部通过。
- `lxml` 使用 `cp311-manylinux_2_26/2_28_x86_64` wheel，其余选择均为纯 Python wheel。
- 这证明一个可用 Linux 环境，不代表所有发行版或 CPU 架构。

### Kylin

当前机器没有 Kylin 镜像或真实 Kylin 环境，因此未做安装与运行实测。纯 Python 组件在满足 Python 版本时风险较低；`lxml` 的 glibc、架构和离线 wheel 可用性仍需在目标 Kylin 版本验证。该限制保留到集成质量门，不能用 Linux Docker 结果替代 Kylin 通过结论。

## 中文与定位结果

统一小样包含“数量范围为 1 至 999，包含边界”“最多两位小数”和“订单编号精确查询”。Windows 与 Linux 均逐字回读成功：

- Markdown：区块具有稳定行范围；
- DOCX：段落、表格单元格和显式分页标记可定位到 OOXML 部件与 XPath；
- PDF：两页文本分别保留页码、内容流顺序、文本矩阵及计算后的文本起点坐标。

## 已知限制

1. DOCX 的页码是排版结果。未运行 Word 渲染时只保留显式分页、分页前和缓存分页标记，不伪造可靠页码。
2. PDF 坐标表示文本起点，并非视觉边框；表格结构、多栏阅读顺序、旋转及复杂字体需要独立验证。
3. 扫描 PDF 和图像不启用 OCR。没有文本层时必须标记为未解析，不能解释成“没有需求”。
4. DOCX 图片、公式、嵌入对象和外部关系只做对象清单与失败报告，不宣称语义理解。
5. Windows 和 Linux 小样由同一脚本生成，但 DOCX ZIP 元数据导致文件哈希可随生成环境变化；可重复性要求适用于冻结输入字节，不要求重新生成的容器文件哈希相同。

## 复现

```powershell
uv sync --extra dev
.venv\Scripts\python.exe scripts\requirement_analysis_dependency_spike.py
.venv\Scripts\python.exe -m pytest tests/unit/test_document_ingestion.py -q
```

脚本与测试只写入 `artifacts/requirement-analysis/` 或测试临时目录，不修改输入资料。
