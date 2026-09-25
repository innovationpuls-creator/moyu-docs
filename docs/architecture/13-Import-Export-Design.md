# Import & Export Design

## 1. 目标

本设计定义系统中的 Import / Export 能力。

本模块解决：

> 外部文件、外部项目和系统内部 Resource 如何安全进入或离开系统，同时保证格式转换、身份、权限、Asset、History、AI、Realtime 和 Resource Lifecycle 不被破坏。

本设计按可上线产品标准设计。

Import / Export 不是：

```text
直接读写数据库
直接复制 Y.Doc
直接拷贝内部存储目录
```

而是系统正式的数据边界。

---

## 2. 第一版产品能力

第一版至少支持：

```text
单 Resource Import
多文件 Import
Folder Import
Project Import
单 Resource Export
Folder Export
Project Export
批量 Export
原始格式 Export
通用格式 Export
Import Preview
Import Validation
Import Conflict Handling
Async Import / Export
Cancel
Retry
Progress
Download Result
```

第一版优先支持：

```text
Markdown
Plain Text
Code Files
Images
Generic Attachments
ZIP Folder / Project Package
```

Document Resource 可以优先支持：

```text
Markdown Import / Export
HTML Export
PDF Export
```

Office 格式：

```text
DOCX
XLSX
PPTX
```

是否第一版实现完整高保真转换，由产品实际需求决定。

架构上必须允许后续扩展。

---

## 3. 核心边界

Import / Export 必须通过正式系统模块完成。

Import 进入：

```text
External Data
↓
Import Pipeline
↓
Validation / Conversion
↓
Resource Lifecycle
↓
Asset
↓
Permission
↓
Persistence
↓
Search / History / Realtime
```

Export 进入：

```text
Resource / Project
↓
Permission
↓
Snapshot / Read View
↓
Export Adapter
↓
Package
↓
Asset / Download
```

不得绕过：

```text
Resource
Permission
Asset
History
Lifecycle
```

直接修改底层数据库。

---

## 4. Import 与 Resource Type

Import 的最终结果必须落到明确的：

```text
Resource Type
```

例如：

```text
.md
→ markdown Resource
或
→ document Resource
```

这不是同一件事。

系统必须区分：

```text
Import as Markdown Source
Import as Rich Document
```

不能产生：

```text
一个 Resource 同时有 Markdown Source 和 Rich Document 两套可写 Source of Truth
```

---

## 5. Import Adapter

每种外部格式通过：

```text
Import Adapter
```

进入系统。

Adapter 至少负责：

```text
格式识别
解析
内容转换
Metadata 提取
Asset 提取
安全检查
生成 Resource Plan
```

例如：

```text
Markdown Import Adapter
Text Import Adapter
Code File Import Adapter
HTML Import Adapter
ZIP Import Adapter
Future DOCX Import Adapter
```

Import Service 不直接理解所有文件格式细节。

---

## 6. Export Adapter

每种目标格式通过：

```text
Export Adapter
```

输出。

Adapter 至少负责：

```text
读取 Resource Read Model
转换
序列化
Asset 处理
Package
生成 Export Result
```

例如：

```text
Markdown Export Adapter
HTML Export Adapter
PDF Export Adapter
Plain Text Export Adapter
Project Package Export Adapter
```

---

## 7. Import Session

每次 Import 创建：

```text
Import Session
```

它表示：

```text
一次导入任务
```

而不是最终 Resource。

至少需要表达：

```text
source
target Workspace
target Project / Folder
initiating user
detected format
import options
status
progress
result
```

---

## 8. Import Session Stage

Import Session 保留自己的 Domain Stage：

```text
Created
Uploading
Inspecting
Validating
ReadyForReview
Importing
Completed
Expired
```

大型 Import 的后台执行状态统一遵守：

```text
25-Async-Task-Execution-Design.md
```

也就是说：

```text
Import Session Stage
!=
Generic Task State
```

`WaitingForUser / Retrying / Failed / Cancelled / PartialSucceeded` 等通用执行语义由 Async Task Runtime 负责。

Import Domain 负责记录：

```text
plan
conflict
item result
partial result
```

---

## 9. Export Session

每次 Export 创建：

```text
Export Session
```

至少表达：

```text
source scope
target format
initiating user
stage
progress
result asset
expiry
```

---

## 10. Export Session Stage

Export Domain Stage：

```text
Created
Preparing
Exporting
Packaging
Ready
Expired
```

大型 Export 的通用执行状态：

```text
Created
Queued
Running
WaitingForUser
Retrying
Succeeded
PartialSucceeded
Failed
Cancelled
```

由：

```text
25-Async-Task-Execution-Design.md
```

统一拥有。

---

## 11. Import Preview

对于可能创建多个 Resource 的导入：

```text
必须支持 Preview
```

例如导入 ZIP：

```text
project.zip
├── README.md
├── src
│   ├── main.ts
│   └── api.ts
└── assets
    └── logo.png
```

Preview 至少展示：

```text
会创建哪些 Folder
会创建哪些 Resource
识别成什么 Resource Type
哪些文件被忽略
哪些文件有冲突
哪些文件不支持
```

---

## 12. Dry Run

Import Preview 应使用：

```text
Dry Run / Import Plan
```

生成。

Dry Run：

```text
不修改正式 Resource
不创建正式 Asset Reference
不改变 Project Tree
```

只产生：

```text
Import Plan
Validation Result
Conflict Result
```

---

## 13. Import Plan

Import Plan 是：

> 导入真正执行前的确定计划。

至少包含：

```text
Target Path
Resource Type
Create / Skip / Rename / Replace decision
Asset mapping
Conflict result
Warnings
```

用户确认后：

```text
Apply Import Plan
```

执行正式导入。

---

## 14. Import Plan 不可静默漂移

当 Preview 已展示给用户后：

```text
Import Plan
```

不能在用户不知情的情况下大幅改变。

如果目标 Project 在等待期间发生变化：

```text
重新 Validate
↓
更新 Conflict
↓
必要时要求重新确认
```

---

## 15. 文件格式识别

Import 不能只相信：

```text
文件扩展名
```

至少结合：

```text
extension
MIME
actual content signature
parser result
```

识别文件。

恶意：

```text
malware.exe → photo.png
```

不能因此绕过安全规则。

---

## 16. 单 Resource Import

用户导入：

```text
README.md
```

系统需要确定：

```text
目标 Folder
Resource Type
Display Name
Import Mode
```

然后创建新的：

```text
resourceId
```

Import 不复用外部文件所谓的 ID 作为系统 Resource Identity。

---

## 17. Import 创建新 Identity

外部导入默认创建新的：

```text
resourceId
nodeId
assetId
```

外部来源中的：

```text
database id
document id
block id
```

不得直接作为本系统可信内部 Identity。

如果系统自己的 Native Export 再 Import：

```text
也必须根据目标场景决定是否保留逻辑关系
```

不能默认无条件复用原 ID。

---

## 18. Node Identity

导入 Document 时：

```text
新创建的可引用结构 Node
```

必须按照 Node Identity Policy 生成新的：

```text
nodeId
```

不得把：

```text
HTML id
Markdown heading index
DOM path
外部 Block ID
```

直接作为本系统 nodeId。

---

## 19. Duplicate / Copy 与 Import 的区别

系统内部：

```text
Duplicate Resource
```

与：

```text
Export → Import
```

语义不同。

Duplicate：

```text
保留更多内部语义
快速复制当前 Resource
```

Export / Import：

```text
跨格式 / 跨系统边界
经过显式序列化和重建
```

不要用 Export / Import 替代内部 Duplicate。

---

## 20. Project Import

Project Import 可以一次创建：

```text
Folder Tree
+
多个 Resource
+
Asset
```

Project Import 是：

```text
Multi Resource Operation
```

必须进入：

```text
Async Task / Operation Coordinator
```

不能以一个巨大同步请求执行。

---

## 21. Project Import 原子性

第一版不声称：

```text
数千 Resource 导入具备全局数据库原子事务
```

但应尽量保证：

```text
Preflight
↓
Create Import Operation
↓
Apply in controlled batches
↓
Record Result
↓
Recover / Retry
```

如果部分成功：

```text
PartiallySucceeded
```

必须明确记录。

---

## 22. Partial Import

Partial Import 时必须展示：

```text
Succeeded
Skipped
Renamed
Failed
```

的对象。

不能只显示：

```text
Import failed
```

而让用户不知道哪些已经进入系统。

---

## 23. Retry Failed

Partial Import 支持：

```text
Retry Failed Items
```

重试不能重复创建：

```text
已经成功的 Resource
```

Import Item 必须具备稳定 Operation Identity 或等价幂等机制。

---

## 24. Cancel Import

用户可以取消尚未完成的大型 Import。

Cancel 后：

- 停止未开始 Item
- 已完成 Item 不假装消失
- 当前 Operation 明确进入 Cancelled / PartiallySucceeded
- 临时文件进入 Cleanup
- 用户可以删除已产生结果或保留结果

不能通过“取消”悄悄回滚已经被其他用户开始使用的 Resource。

---

## 25. Import Permission

正式 Import 前必须检查：

```text
Create Resource
Create Folder
Upload Asset
目标 Project / Folder Access
Quota
```

如果 Import Plan 包含：

```text
Replace / Trash
```

还需要对应更高权限。

---

## 26. Import 期间权限变化

用户发起 Import 后可能被降权。

正式创建每个批次前必须确认：

```text
当前权限仍有效
目标 Lifecycle 仍有效
```

不能只在 Session 创建时检查一次。

---

## 27. Target Lifecycle

Import 目标不能是：

```text
Trashed Project
Deleted Folder
PendingDeletion Workspace
```

如果 Import 运行期间目标进入不可写状态：

```text
停止后续写入
↓
Task 进入明确失败 / Partial 状态
```

---

## 28. 名称冲突

Import 时同级可能已经存在：

```text
README.md
```

第一版需要支持至少：

```text
Skip
Rename Imported
Replace Existing
```

其中：

```text
Replace Existing
```

是高风险操作。

不得默认静默覆盖。

---

## 29. Replace Existing

Replace Existing 不应该：

```text
直接复用外部二进制覆盖数据库
```

而应走：

```text
Resource Type Import
↓
受控 Resource Change
↓
History
↓
Realtime
```

如果目标 Resource 正在多人编辑：

```text
必须避免静默覆盖当前修改
```

---

## 30. Replace Existing 默认策略

第一版建议：

```text
默认不 Replace
```

用户明确选择时才允许。

大量导入时：

```text
Skip / Auto Rename
```

比隐式覆盖安全。

---

## 31. Replace 与 ChangeSet

对于：

```text
替换已有 Resource 内容
```

建议复用：

```text
ChangeSet / Operation
```

能力。

先生成：

```text
Preview / Diff
```

再 Apply。

这样可以统一：

```text
冲突检查
权限
History
幂等
```

---

## 32. Markdown Import

Markdown Import 至少支持：

```text
Heading
Paragraph
List
Code Block
Quote
Link
Image Reference
```

如果导入为 Rich Document：

```text
Markdown
↓
Document Schema
↓
Node Identity
↓
Y.Doc
```

转换失败的结构需要：

```text
Fallback
Warning
```

而不是整份文件直接丢失。

---

## 33. Markdown Source Import

如果用户选择：

```text
Import as Markdown Resource
```

则：

```text
Markdown Source
```

本身就是正文。

不再同时创建一套独立可写 Rich Document Source。

---

## 34. HTML Import

HTML Import 必须进行：

```text
Sanitization
```

不能执行：

```text
script
inline dangerous event
unsafe embed
```

外部 HTML 是不可信输入。

只转换允许的结构和内容。

---

## 35. Code Import

Code File Import：

```text
文件内容
→ Code / Text Resource
```

需要：

```text
Encoding Detection
Binary Detection
Language Detection（可选）
```

不能把：

```text
二进制文件
```

误当代码文本。

---

## 36. Text Encoding

Import 必须正确处理常见：

```text
UTF-8
UTF-8 BOM
UTF-16
```

等编码。

无法可靠识别时：

```text
进入 Warning / User Choice
```

不能静默产生乱码。

---

## 37. Line Ending

Code / Text Import 应识别：

```text
LF
CRLF
```

内部可以统一处理。

Export 时可以根据：

```text
Target Format / User Option
```

决定输出。

不能因为行尾格式导致正文逻辑变化。

---

## 38. Binary File Import

非正文二进制：

```text
Image
Video
Audio
PDF
Archive
Generic File
```

进入：

```text
Asset Pipeline
```

而不是创建：

```text
Y.Text Resource
```

除非产品定义该格式有正式 Resource Type。

---

## 39. Asset Import

Import 内的 Asset 必须复用：

```text
Asset & File Storage Design
```

能力，包括：

```text
Upload / Ingest
Content Type Validation
Hash
Security Scan
Processing
assetId
```

Import 不能建立第二套 Asset Storage。

---

## 40. ZIP Import

ZIP Import 必须防止：

```text
Zip Bomb
Path Traversal
Absolute Path
../ Escape
Extreme File Count
Extreme Nesting
Duplicate Path
Unsupported Encryption
```

不能直接：

```text
unzip -o
```

到服务器工作目录。

---

## 41. Archive Limits

Archive Import 至少限制：

```text
compressed size
expanded size
file count
nesting depth
single file size
processing time
```

具体数值由产品和部署环境决定。

---

## 42. Symlink

导入 Archive 时：

```text
symlink
hard link
device file
```

默认不作为普通文件导入。

除非后续明确设计。

第一版应：

```text
ignore / block
```

并给出 Warning。

---

## 43. Hidden Files

Project / Folder Import 对：

```text
.dotfiles
```

是否导入由产品规则决定。

代码项目通常需要支持：

```text
.gitignore
.env.example
.editorconfig
```

但：

```text
.env
private keys
credential files
```

需要安全提醒或默认阻止策略。

---

## 44. Secret Detection

代码 / Project Import 应预留：

```text
Secret Detection
```

用于识别：

```text
Private Key
Access Token
Password
Credential File
```

第一版至少可以：

```text
Warning
```

后续可增加：

```text
Block / Redact
```

策略。

Import 不能把安全敏感文件悄悄发送到 AI / Search。

---

## 45. Ignore Rules

Project Import 可以支持：

```text
Ignore Rules
```

例如：

```text
.git
node_modules
dist
build
cache
temporary files
```

默认规则应适合常见工程项目。

用户可以在 Preview 中看到被忽略对象。

---

## 46. Import 不建立 Git 语义

导入一个 Git Repository 的文件：

```text
不等于导入 Git History
```

第一版只导入：

```text
Current File Tree
```

Git Commit / Branch / Remote 以后如果需要，单独设计。

---

## 47. External URL Import

未来可以支持：

```text
Import from URL
```

但必须经过：

```text
SSRF Protection
Allowlist / Network Policy
Size Limit
Content Type Check
Redirect Limit
Timeout
```

第一版可以不开放任意 URL Import。

---

## 48. Cloud Provider Import

未来可接：

```text
Google Drive
Dropbox
OneDrive
GitHub
Notion
```

但都应适配成：

```text
External Source Adapter
↓
Import Plan
↓
正式 Import Pipeline
```

外部 Connector 不直接写数据库。

---

## 49. Import Source Provenance

Import 可以记录：

```text
sourceType
originalName
importedAt
initiatingUser
source metadata
```

用于：

- Audit
- Debug
- 用户理解来源

但不应保存：

```text
不必要的外部 Secret
长期有效 Access Token
```

---

## 50. Import 与 History

新 Resource Import 成功后：

```text
History 从 Import 创建时开始
```

可以记录：

```text
Created by Import
```

默认不把：

```text
外部系统历史
```

伪装成本系统原生 History。

---

## 51. Native Package Import

系统自己的 Native Export Package 可以携带：

```text
Resource Content
Folder Tree
Asset Manifest
Metadata
Optional History
Schema Version
```

用于：

```text
Backup-like portability
Workspace migration
offline transfer
```

但 Native Package Import 仍必须：

```text
Validate
Permission Check
Identity Rebuild / Mapping
```

不能信任包内所有内部 ID。

---

## 52. Native Package Version

Native Export Package 必须带：

```text
packageVersion
schemaVersion
```

Import 时：

```text
检查兼容性
```

旧版本可以通过：

```text
Migration Adapter
```

导入。

无法兼容时应明确拒绝。

---

## 53. Identity Mapping

Native Package Import 需要建立：

```text
Old ID
→
New ID
```

Mapping。

至少包括：

```text
resourceId
nodeId
assetId
```

这样内部引用可以重写。

默认不直接复用来源系统 ID。

---

## 54. Cross Resource Reference

如果 Resource A 引用 Resource B：

```text
Native Package Export
```

可以记录逻辑 Reference。

Import 时：

```text
Old ResourceRef
↓
Identity Mapping
↓
New ResourceRef
```

如果目标未被导入：

```text
保留为 Broken / External Reference
或
明确 Warning
```

不能错误指向其他 Resource。

---

## 55. External Link

普通 Markdown / HTML 中的外部 URL：

```text
默认保持 External Link
```

不自动下载整个互联网内容。

如果需要：

```text
Fetch & Embed
```

应由用户明确选择。

---

## 56. Export 权限

Export 前必须检查：

```text
Read Resource
Download Asset
Export Capability
```

Project / Workspace Export 需要更高 Scope 权限。

不能因为用户能看到某一个 Resource，就允许导出整个 Workspace。

---

## 57. Export 与当前状态

普通 Export 默认基于：

```text
导出开始时确定的 Resource Read State
```

大型 Project Export 运行期间用户仍可继续编辑。

Export 结果不要求锁住整个 Project。

---

## 58. Export Snapshot

为了保证导出内容自洽：

```text
Export Session
```

应使用：

```text
Stable Read View
```

或等价 Snapshot 语义。

这不是 Yjs Snapshot 产品概念。

只是：

> 导出任务读取一份确定的数据视图。

---

## 59. Export 不锁编辑

Export 过程中：

```text
不能长时间锁 Resource
不能要求用户停止编辑
```

用户继续正常协作。

导出结果代表：

```text
Export Session 所选定的读取状态
```

---

## 60. 单 Resource Export

单 Resource Export 至少支持：

```text
Native Format
Text-friendly Format
```

例如：

```text
Document
→ Markdown / HTML / PDF

Markdown
→ .md

Code
→ source file

Text
→ .txt
```

具体支持矩阵由 Resource Type Adapter 定义。

---

## 61. Export Adapter 与 Resource Type

每个 Resource Type 需要声明：

```text
supported export formats
```

例如：

```text
Document:
  markdown
  html
  pdf

Code:
  source

Markdown:
  markdown
  html

Text:
  text
```

Export Service 不自己理解 Document Schema。

---

## 62. PDF Export

PDF Export 是：

```text
Rendering
```

不是 Resource Source of Truth。

PDF 失败：

```text
不影响 Resource
```

大型或复杂 PDF 生成进入 Async Task。

---

## 63. HTML Export

HTML Export 必须：

- 输出安全结构
- 正确转义
- 明确 Asset URL / Package Strategy
- 不携带内部 Secret
- 不暴露内部服务地址

---

## 64. Markdown Export

Rich Document → Markdown 属于：

```text
Lossy or Partially Lossy Conversion
```

因为某些 Rich Node 未必有标准 Markdown 表达。

系统必须：

```text
尽可能保留语义
+
对无法完全表达的结构使用明确 Fallback
```

不能假装所有格式 100% 无损。

---

## 65. Fidelity

Export Adapter 应定义：

```text
Lossless
Best Effort
Lossy
```

级别。

例如：

```text
Markdown Resource → Markdown
= Lossless

Rich Document → Markdown
= Best Effort

Rich Document → Plain Text
= Lossy
```

产品可以在必要时提示用户。

---

## 66. Export Asset

Document / Project Export 需要处理 Asset。

至少支持两种策略：

```text
Package Assets
External References
```

第一版 Project / Folder Export 建议：

```text
Package Assets
```

形成可携带 Archive。

---

## 67. Asset Manifest

Package Export 需要建立：

```text
Asset Manifest
```

至少记录：

```text
assetId
export path
content type
size
hash
```

包内 Resource 只引用导出的相对路径或 Manifest Entry。

不能写入：

```text
临时 Signed URL
```

作为可移植文件。

---

## 68. Export Package

Folder / Project Export 推荐形成：

```text
ZIP / Native Package
```

内容可以包括：

```text
manifest
folder tree
resource files
assets
metadata
```

具体 Native Package Layout 由实现定义。

必须版本化。

---

## 69. Export Package 安全

Export 的 Archive：

```text
文件名
路径
Metadata
```

必须进行安全规范化。

不能生成：

```text
../
absolute path
device path
```

等危险路径。

---

## 70. Export File Name

导出文件名支持 Unicode。

同时需要：

```text
cross-platform safe name
```

策略。

Windows / macOS / Linux 对非法字符和保留名不同。

Package 内可以：

```text
display name
+
safe path
+
manifest mapping
```

分离。

---

## 71. Name Collision

导出到文件系统时：

```text
两个逻辑名称
```

可能经过跨平台规范化后冲突。

Export 必须：

```text
自动生成唯一安全路径
+
保留 Manifest Mapping
```

不能静默覆盖。

---

## 72. Project Export

Project Export 至少包含：

```text
Folder Tree
Resource Content
Asset
Basic Metadata
```

可选：

```text
Named History Version
Comments
Audit
Full History
```

第一版普通用户 Project Export 不默认包含完整 Audit / History。

---

## 73. Workspace Export

Workspace 全量 Export 属于高成本、高权限操作。

第一版可以：

```text
仅管理员 / Owner
+
Async Task
+
明确 Scope
```

如果产品暂时不需要，可以不开放 UI。

架构需预留。

---

## 74. Export 与 History

普通 Resource Export 默认导出：

```text
Current State
```

History Export 是独立选项。

不能：

```text
用户点 Download
↓
自动打包几年所有历史
```

造成巨大文件和隐私问题。

---

## 75. Export 与 Comment

Comments 是否导出由：

```text
Format
Product Option
Permission
```

决定。

例如：

```text
PDF review export
```

可以选择包含评论。

普通 Markdown Export 默认不一定包含 Comment。

---

## 76. Export 与 Permission 变化

大型 Export 期间用户权限可能被撤销。

在真正读取后续 Resource / Asset 时：

```text
需要确认当前访问仍有效
```

对于已经写入临时 Export Package 的数据：

```text
如果权限撤销
```

Task 应安全停止并清理未发布结果。

---

## 77. Export Result

完成后的 Export Result 应作为：

```text
短期可下载结果
```

可以存入：

```text
Asset / Temporary Object
```

并设置：

```text
Expiry
```

不应永久占用存储。

---

## 78. Export Download URL

下载使用：

```text
短期 Signed URL
```

或等价受控访问能力。

不能：

```text
永久公开 Export File
```

---

## 79. Export Result Retention

Export Result 应自动过期。

过期后：

```text
重新 Export
```

而不是永久保存所有临时 ZIP / PDF。

具体 Retention 由部署策略决定。

---

## 80. Import Temp Storage

导入原始文件和临时解压内容必须有：

```text
Temporary Storage
```

并自动 Cleanup。

不能把临时文件永久留在：

```text
应用服务器本地磁盘
```

---

## 81. Temp Isolation

不同 Import Task 的临时内容必须隔离。

不能：

```text
Task A
```

意外读取：

```text
Task B
```

临时文件。

---

## 82. Malware Scan

Import 的所有二进制输入必须复用 Asset Security Pipeline。

Archive 解压后的文件也需要按策略检查。

不能：

```text
只扫描 ZIP 本身
```

却完全信任内部内容。

---

## 83. Import HTML / Script 安全

任何可执行式内容：

```text
HTML
SVG
Script
Macro
```

都必须按安全策略处理。

Import 只提取：

```text
被允许的内容语义
```

不执行来源中的代码。

---

## 84. DOCX / Office Macro

如果未来支持 Office Import：

```text
Macro
ActiveX
Embedded executable
```

默认不执行。

格式转换必须在安全隔离环境运行。

---

## 85. Conversion Sandbox

复杂第三方解析器：

```text
Office
PDF
Image
Media
Archive
```

可能处理恶意输入。

高风险转换应运行在：

```text
isolated worker / sandbox
```

限制：

```text
CPU
Memory
Time
Filesystem
Network
```

避免 parser vulnerability 影响主后端。

---

## 86. Import Size Limit

至少限制：

```text
单文件大小
总 Import 大小
文件数量
Folder 深度
Resource 数
Asset 数
解析时间
```

防止用户通过 Import 一次创建不可控规模的数据。

---

## 87. Export Size Limit

大型 Export 需要：

```text
Size Estimate
```

或等价保护。

超过产品策略时：

```text
Split Export
Admin Export
Reject with clear reason
```

不能无限打包直到 Worker OOM。

---

## 88. Quota

Import 正式执行前：

```text
预估新增 Resource
预估 Asset Storage
预估 Project Size
```

并检查 Quota。

如果无法精确预估：

```text
执行过程中持续检查
```

超过 Quota 时：

```text
停止后续 Item
```

并产生明确 Partial Result。

---

## 89. Backpressure

大量 Import / Export 并发时：

```text
必须 Queue
```

并根据：

```text
Workspace
User
Worker Capacity
Storage Capacity
```

进行公平调度。

不能让 1 个超大 Project Export 占满所有 Worker。

---

## 90. Parallelism

大型 Import 可以并行处理互不依赖的文件。

例如：

```text
100 个 Code Resource
```

可并行解析 / 创建。

但：

```text
Folder dependency
Cross Resource reference
Quota
Operation order
```

需要协调。

不要无脑单线程，也不要无上限并行。

---

## 91. Idempotency

以下操作必须具备幂等：

```text
Start Import
Apply Import Plan
Create Import Item
Retry Failed Item
Start Export
Publish Export Result
```

网络重试不能：

```text
重复创建 100 个 Resource
重复扣 Quota
重复生成多个正式 Export Result
```

---

## 92. Import Item Identity

一个 Import Session 内：

```text
每个计划项
```

需要稳定 Item Identity。

用于：

- 重试
- 状态查询
- Partial Result
- Audit
- Idempotency

它不是 Resource ID。

---

## 93. Export Consistency

Project Export 必须保证：

```text
每个 Resource 输出自身一致状态
```

第一版不要求整个 Project 在一个纳秒级全局原子时刻冻结。

如果未来需要：

```text
Release Snapshot
```

由更高层 Release / Snapshot 产品设计。

---

## 94. Import Event

Import 模块遵守 Unified Module Communication Design。

至少产生：

```text
ImportStarted
ImportPlanReady
ImportItemSucceeded
ImportItemFailed
ImportCompleted
ImportPartiallySucceeded
ImportCancelled
```

---

## 95. Export Event

至少产生：

```text
ExportStarted
ExportReady
ExportFailed
ExportCancelled
ExportExpired
```

---

## 96. Command

典型 Command：

```text
CreateImportSession
CreateImportPlan
ApplyImportPlan
CancelImport
RetryImportItem

CreateExport
CancelExport
RetryExport
```

---

## 97. Query

典型 Query：

```text
GetImport
GetImportPlan
GetImportProgress
GetImportResult

GetExport
GetExportProgress
GetExportResult
```

---

## 98. Progress

大型 Import / Export 必须提供：

```text
progress
```

但进度不是系统真相。

最终状态以：

```text
Task / Operation State
```

为准。

进度可以：

```text
近似
```

不能因为百分比计算困难就阻塞任务执行。

---

## 99. Error Model

Import 至少区分：

```text
Unsupported Format
Corrupt File
Invalid Encoding
Unsafe Archive
Malware Detected
Permission Denied
Quota Exceeded
Name Conflict
Target Deleted
Parse Failed
Conversion Failed
Asset Failed
Partial Import
```

Export 至少区分：

```text
Permission Denied
Unsupported Format
Source Deleted
Asset Missing
Conversion Failed
Package Failed
Too Large
Export Expired
Storage Unavailable
```

统一遵守系统 Error Model。

---

## 100. Observability

至少监控：

```text
import count
import bytes
import duration
import queue wait
import failure rate
import partial success
import item retry
parse duration
conversion duration
malware block
archive rejection
secret warning
quota rejection
resource created by import
asset created by import
export count
export bytes
export duration
export failure
export package size
export result expiry
temp storage usage
temp cleanup failure
worker saturation
```

---

## 101. Audit

至少审计：

```text
Project Import
Large Batch Import
Replace Existing
Cross Workspace Native Import
Project Export
Workspace Export
Sensitive Export
Admin Export
```

普通单文件 Import / Export 是否进入长期安全 Audit 由产品策略决定。

---

## 102. Search 联动

Import 创建 Resource 后：

```text
Search
```

通过正常 Resource Event 异步建立索引。

Import 不直接写 Search Engine。

Export 不依赖 Search Index 读取正文。

---

## 103. AI 联动

AI 可以帮助：

```text
解释 Import Warning
建议 Resource Type
生成 Import Mapping
总结 Export Content
```

但：

```text
AI 不是 Parser 权威
AI 不能决定安全扫描结果
AI 不能绕过 Permission
```

---

## 104. History 联动

Import 创建的新 Resource：

```text
History
```

从导入成功开始。

Replace Existing：

```text
必须进入正常 History
```

Export 不产生 Resource Content History，除非导出本身改变系统状态。

---

## 105. Realtime 联动

新 Resource Import 完成后：

```text
进入正常 Resource Collaboration
```

Replace Existing 时：

```text
修改必须进入正常 Realtime 路径
```

不能：

```text
后台 Import 覆盖数据库
↓
在线用户不知道
```

---

## 106. Permission 联动

Import / Export 所有 Scope 都经过统一 Permission。

尤其：

```text
Folder Export
Project Export
Workspace Export
Replace Existing
Cross Project Import
```

不能仅靠 UI 隐藏入口。

---

## 107. Asset 联动

所有导入二进制：

```text
进入 Asset Pipeline
```

所有导出资源附件：

```text
通过 Asset Read API
```

Import / Export 不直接访问 Object Storage Secret。

---

## 108. Lifecycle 联动

Import 创建对象必须通过：

```text
Resource Lifecycle
```

Export 读取对象必须确认：

```text
Resource / Project Lifecycle
```

Trash / Deleted 默认不进入普通 Export，除非用户在 Trash Scope 明确执行。

---

## 109. Backup 与 Export 的区别

普通 Export：

```text
用户可携带格式
```

Backup：

```text
系统灾难恢复
```

两者不是一回事。

不能把：

```text
用户 ZIP Export
```

当成生产 Backup / DR 方案。

---

## 110. Native Export 与 Backup

Native Package 可以提升数据可移植性。

但 Backup 还需要：

```text
Database
Object Storage
Journal
Checkpoint
Metadata
Encryption
Recovery Point
Recovery Procedure
```

后续由 Disaster Recovery Design 统一定义。

---

## 111. Privacy

Export 是敏感数据外流边界。

系统需要：

- Permission
- Audit
- Scope
- Expiring Result
- No Secret Leakage
- Asset Access Check

未来企业版可以增加：

```text
Export Disabled
Admin Approval
Watermark
DLP
```

架构上需可扩展。

---

## 112. 第一版不做

第一版暂不要求：

```text
完整 Git History Import
任意第三方 SaaS 双向同步
Office 100% 像素级无损往返
跨 Workspace 自动 ID 保留
任意 URL 无限制抓取
自动执行外部脚本 / Macro
把用户 Export 当 Backup
全局分布式原子 Import
```

---

## 113. 核心验收场景

### 场景 1：Markdown Import

用户导入：

```text
architecture.md
```

选择：

```text
Import as Rich Document
```

结果：

- 创建新 resourceId
- Markdown 转换为 Document Schema
- 结构 Node 获得新 nodeId
- 图片进入 Asset Pipeline
- Search 异步索引
- 可以正常多人协作

---

### 场景 2：Markdown Source Import

同一个文件选择：

```text
Import as Markdown
```

结果：

- 创建 Markdown Resource
- Markdown 文本是唯一正文 Source
- 不同时维护另一套 Rich Document Source

---

### 场景 3：ZIP Project Import

ZIP 中有：

```text
src/
docs/
README.md
logo.png
```

结果：

- 先生成 Import Preview
- 展示 Folder / Resource / Asset 计划
- 用户确认
- 异步执行
- Progress 可查询

---

### 场景 4：Archive Path Traversal

ZIP 包含：

```text
../../etc/passwd
```

结果：

```text
拒绝危险 Entry
```

不能写出 Import Sandbox。

---

### 场景 5：Zip Bomb

小压缩包解压后规模异常。

结果：

- Expansion Limit 生效
- Import Block
- Worker 不被耗尽

---

### 场景 6：Name Conflict

目标 Folder 已有：

```text
README.md
```

结果：

- Preview 明确冲突
- 默认不覆盖
- 可选择 Skip / Rename / Explicit Replace

---

### 场景 7：Replace Existing

用户明确 Replace 一个正在协作的 Resource。

结果：

- 进入受控 Change / ChangeSet
- 重新检查当前状态
- Preview Diff
- Apply 进入 Realtime / History
- 不直接数据库覆盖

---

### 场景 8：Partial Import

100 个文件中：

```text
95 成功
5 失败
```

结果：

```text
PartiallySucceeded
```

用户可看到失败项并单独 Retry。

已成功项不重复创建。

---

### 场景 9：Cancel Import

导入大型 Project 中途取消。

结果：

- 未开始项停止
- 已成功 Resource 保留
- 临时文件最终清理
- 状态明确
- 不假装全量回滚

---

### 场景 10：Import 期间降权

用户开始导入时有权限。

执行期间被移除 Project。

结果：

- 后续写入停止
- 当前 Task 明确失败 / Partial
- 不继续凭旧权限创建 Resource

---

### 场景 11：单 Resource Export

Document 导出 Markdown。

结果：

- 不锁住实时编辑
- 读取一个确定状态
- Asset 以可携带方式处理
- 下载结果短期有效

---

### 场景 12：Rich Document → Markdown

Document 包含 Markdown 无法完整表达的特殊 Block。

结果：

- Export 采用明确 Fallback
- 不无声丢掉整块内容
- 产品可提示 Best Effort

---

### 场景 13：Project Export

大型 Project Export。

结果：

- Async Task
- 用户继续编辑
- Progress 可查询
- 文件树与 Asset 正确打包
- 不把 Signed URL 写入包

---

### 场景 14：Export 权限撤销

大型 Export 进行中。

用户权限被撤销。

结果：

- 后续敏感读取停止
- 未发布结果清理
- 不向用户继续提供最终下载

---

### 场景 15：Cross-platform Name

Project 中有中文和特殊文件名。

Export 到 ZIP。

结果：

- 名称可读
- 路径安全
- 发生平台冲突时生成唯一安全路径
- Manifest 保留映射

---

### 场景 16：Native Package Import

导入系统自己的 Native Package。

结果：

- 校验 packageVersion
- 生成新的 ID Mapping
- 重写 ResourceRef / NodeRef / AssetRef
- 不盲目信任原始内部 ID

---

### 场景 17：External Secret

Project Import 中包含：

```text
.env
private-key.pem
```

结果：

- 触发安全 Warning / Policy
- 不静默进入 AI / Search Context

---

### 场景 18：Conversion Worker 崩溃

复杂格式转换 Worker 崩溃。

结果：

- 主 Realtime / Permission / Persistence 正常
- Task 可 Retry
- 临时文件最终清理

---

### 场景 19：Storage Failure

Export Package 写 Object Storage 失败。

结果：

- Export 不标记 Ready
- 用户收到明确失败
- Resource 无变化
- 可 Retry

---

### 场景 20：高并发

多个 Workspace 同时进行大 Import / Export。

结果：

- Queue + Backpressure
- 有公平并发控制
- 不无限占用 CPU / Memory
- Realtime 主链保持正常

---

## 114. 本地 AI 实现自由度

本设计不规定：

- 使用哪一种 Archive 库
- Import / Export Worker 框架
- Temp Storage 产品
- Native Package 具体目录结构
- Import Plan 数据表结构
- 转换库
- PDF Renderer
- DOCX Parser
- Secret Scanner 产品
- Malware Scanner 产品
- 并发 Worker 数量
- Retry 次数
- Archive Limit 具体数值
- Export Result 保留时间
- Progress 计算方式

本地 AI 可以根据项目技术栈、部署环境和压力测试选择。

但必须满足本设计的功能、安全、身份、并发、权限、恢复和可移植性要求。

---

## 115. 架构硬约束

1. Import / Export 是正式系统边界，不直接读写业务数据库内部结构。
2. Import 最终必须落到明确 Resource Type。
3. 不允许一个 Resource 同时维护两个可写 Source of Truth。
4. Import / Export 必须使用 Adapter 扩展不同格式。
5. 多文件 Import 必须先支持 Preview / Import Plan。
6. Import Plan 正式执行前必须重新 Validate。
7. 外部 ID 默认不能直接作为内部 resourceId / nodeId / assetId。
8. Document Import 必须遵守 Node Identity Policy。
9. Import 创建 Resource 必须经过 Resource Lifecycle。
10. 二进制 Import 必须经过 Asset Pipeline。
11. HTML / Archive / Office 等不可信输入必须经过安全处理。
12. ZIP Import 必须防 Path Traversal、Zip Bomb 和异常文件数量。
13. 大型 Import / Export 必须使用 Async Task。
14. Partial Import / Export Failure 必须有明确状态和可恢复路径。
15. Import Item / Export Session 必须具备幂等保护。
16. Replace Existing 默认不能静默执行。
17. Replace Existing 必须进入正常 Resource Change / History / Realtime 路径。
18. Import / Export 期间必须重新检查当前 Permission 和 Lifecycle。
19. Import / Export 不得阻塞 Realtime Collaboration。
20. Export 必须使用稳定 Read View，不长时间锁住 Resource。
21. Export Package 不能包含临时 Signed URL 作为永久引用。
22. Native Package 必须版本化。
23. Native Package Import 必须进行 Identity Mapping。
24. Cross Resource Reference Import 必须正确重写或明确 Broken。
25. Export Result 必须短期存储并自动过期。
26. Temp Import / Export 数据必须自动 Cleanup。
27. 高风险第三方 Parser 应在隔离 Worker / Sandbox 运行。
28. Import / Export 必须支持 Quota、Rate Limit、Backpressure 和可观测性。
29. Export 不能成为绕过权限的数据外流后门。
30. Import / Export 模块遵守 Unified Module Communication Design。

---

## 116. 最终模型

Import：

```text
External Source
      │
      ▼
Import Session
      │
      ▼
Inspect / Validate
      │
      ▼
Import Plan
      │
      ▼
Preview
      │
      ▼
Apply
      │
      ├── Folder / Project
      ├── Resource Lifecycle
      ├── Resource Type Adapter
      ├── Asset
      └── Identity Mapping
              │
              ▼
        Normal System Path
              │
              ├── Realtime
              ├── Persistence
              ├── History
              ├── Search
              └── Audit
```

Export：

```text
Resource / Project
      │
      ▼
Permission
      │
      ▼
Stable Read View
      │
      ▼
Export Adapter
      │
      ├── Resource Content
      ├── Asset
      └── Metadata
              │
              ▼
          Package
              │
              ▼
       Temporary Export Asset
              │
              ▼
       Expiring Download
```

系统必须保证：

> Import 负责把外部数据安全地变成系统正式对象，Export 负责把系统正式对象安全地变成可携带结果。两者都不能绕过既有 Resource、Permission、Asset、Realtime、Persistence 和 History 边界。
