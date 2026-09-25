# Asset & File Storage Design

## 1. 目标

本设计定义系统中图片、视频、音频、附件和其他大型二进制文件的上传、存储、访问、引用、预览、删除与长期生命周期。

本模块解决：

> 二进制文件如何安全、高效地进入系统，如何被 Resource 引用，如何避免阻塞实时协作，如何在权限、删除、复制和恢复场景下保持正确，并支持生产环境中的大文件、失败重试、扫描、CDN 和垃圾回收。

本模块不负责：

- Document / Code 的正文协作
- Yjs CRDT 同步
- Resource Tree
- Permission 的基础角色定义
- History 的正文版本逻辑
- Search 的完整索引设计

这些分别由已有模块负责。

---

## 2. 核心边界

Asset 与 Resource 必须分离。

```text
Resource
= 可实时协作对象

Asset
= 可被 Resource 引用的二进制对象
```

例如：

```text
Document Resource
└── image node
    └── assetId

Code Resource
└── attachment reference
    └── assetId
```

正文只保存：

```text
assetId
```

或等价稳定引用。

不得把：

```text
base64
signed URL
临时 CDN URL
本地文件路径
二进制内容
```

直接写入 Y.Doc。

---

## 3. Asset 不是实时协作边界

Asset 本身不创建：

```text
Y.Doc
Awareness
Resource Session
```

Asset 的实时变化通过：

```text
Resource Metadata / Event / Task
```

传播。

例如图片上传处理中：

```text
Uploading
↓
Processing
↓
Ready
```

可以通过统一 Event / Query 更新 UI。

---

## 4. 第一版正式支持的文件类型

第一版至少支持：

```text
Image
Video
Audio
Generic Attachment
```

可选扩展：

```text
PDF
Archive
Office File
Font
Model / Dataset
```

是否允许某类文件由产品和安全策略决定。

Asset 系统不应把文件扩展名当作唯一类型依据。

---

## 5. 用户可见能力

第一版至少提供：

- 上传文件
- 拖拽上传
- 粘贴图片
- 上传进度
- 取消上传
- 失败重试
- 大文件断点续传
- 上传完成后插入 Resource
- 文件预览
- 下载
- 重命名显示名
- 替换引用
- 删除引用
- 查看上传失败原因
- Resource Duplicate 时复用 Asset
- Trash / Restore 时保持引用
- Permanent Delete 后按策略回收

---

## 6. 上传主流程

推荐产品流程：

```text
Client
↓
请求创建 Upload Session
↓
服务端鉴权 / Quota / 文件策略检查
↓
Client 直接上传 Object Storage
↓
完成上传
↓
完整性校验
↓
安全扫描 / 类型识别
↓
生成必要派生文件
↓
Asset Ready
↓
Resource 使用 assetId 引用
```

大文件不应默认经应用服务器完整转发。

---

## 7. Direct Upload

生产环境优先采用：

```text
Client
→ Object Storage
```

直接上传。

应用服务负责：

- 授权
- 创建上传会话
- 限制大小与类型
- 签发短期上传权限
- 完成确认
- 后处理
- Asset Metadata

这样可以避免：

```text
所有大文件
→ API Server
→ 再转发 Storage
```

造成应用服务器带宽和内存瓶颈。

---

## 8. Upload Session

每次上传应存在独立 Upload Session。

它负责表达：

```text
上传目标
当前状态
目标 Workspace
预期文件大小
预期文件类型
上传者
过期时间
```

Upload Session 是短生命周期对象。

它不是 Asset 本身。

上传失败或长期未完成后可以自动过期。

---

## 9. Upload 状态

至少需要表达：

```text
Created
Uploading
Uploaded
Verifying
Processing
Ready
Failed
Cancelled
Expired
Blocked
```

只有：

```text
Ready
```

状态的 Asset 才能作为正常可用文件对外提供。

---

## 10. 大文件与断点续传

系统必须支持大文件。

具体大小上限由产品、部署和套餐决定。

对于超过普通单请求适合范围的文件，应支持：

```text
Multipart Upload
Resumable Upload
Chunk Retry
```

网络中断后不能强制用户从 0 开始重新上传大型文件。

正式实现使用 `S3-compatible Multipart Upload + Signed URL`；具体分片大小、并发数和重试参数由运行配置决定，不再由本地 AI 自行替换上传协议。

---

## 11. 上传不阻塞编辑

文件上传不得阻塞 Resource 的正文协作。

例如用户在 Document 中插入图片：

```text
创建 Pending Asset
↓
Document 可立即显示上传占位状态
↓
后台上传
↓
Asset Ready
↓
UI 更新
```

其他用户仍然可以继续编辑 Document。

---

## 12. Pending Asset

对于需要先在正文中占位再上传的场景，可以创建：

```text
Pending Asset Reference
```

但必须保证：

- 失败后可恢复或移除
- 不把临时上传 URL 写入 Y.Doc
- 最终转换为稳定 assetId
- Pending 状态不能永久遗留

具体占位结构由 Resource Type 实现决定。

---

## 13. 稳定 Asset Identity

每个逻辑 Asset 使用稳定：

```text
assetId
```

作为系统引用身份。

用户显示文件名、Object Storage Key、CDN URL 均不能替代 assetId。

文件位置变化后：

```text
assetId
```

保持不变。

---

## 14. Asset 与 Blob 分离

生产设计建议区分：

```text
Asset
= 产品中的逻辑文件对象

Blob
= 底层实际二进制内容
```

关系：

```text
Asset
└── Blob
```

多个 Asset 可以在安全策略允许时复用同一 Blob。

这样可以支持：

- 去重
- Duplicate Resource 不复制大文件
- 多个引用共享文件内容
- Blob 生命周期独立管理

具体数据库结构由本地 AI 决定。

---

## 15. Blob 不暴露给业务模块

业务模块只使用：

```text
assetId
```

不长期保存：

```text
bucket
object key
storage provider id
physical path
```

这些属于 Asset Storage 内部实现。

未来更换 Object Storage 时不应要求修改 Document / Resource Schema。

---

## 16. 文件名

用户文件名必须原生支持 Unicode。

例如：

```text
系统架构图.png
需求评审录音.m4a
设计稿最终版.pdf
```

内部存储 Key 不依赖用户文件名。

显示名与物理存储名分离。

---

## 17. Content Type

不得只信任：

```text
file extension
client MIME
```

系统应根据实际文件内容进行类型识别或验证。

客户端声明可以作为提示。

最终可用类型由服务端安全检查确定。

---

## 18. 文件完整性

上传完成后必须校验：

- 实际文件大小
- Upload Session 预期大小
- Storage 是否完整
- 必要 Hash / Checksum

大文件分片上传必须确认所有必要 Part 完成。

不能因为客户端声称：

```text
upload success
```

就直接标记 Ready。

---

## 19. Hash

系统应为 Blob 计算稳定内容 Hash。

Hash 可用于：

- 完整性校验
- 去重
- 缓存
- 重复上传识别

具体算法由本地 AI 选择成熟安全方案。

不要使用弱 Hash 作为安全依据。

---

## 20. 去重

允许对相同二进制内容进行底层去重。

但去重必须保持租户 / Workspace 安全边界。

不能因为全局存在相同 Hash 就向用户暴露：

```text
另一个 Workspace 已上传过该文件
```

去重属于存储优化，不是产品可见跨租户共享。

---

## 21. Workspace 级逻辑所有权

Asset 的逻辑访问范围至少绑定到：

```text
Workspace
```

Resource 引用 Asset 时必须满足：

```text
Resource 所属 Workspace
与
Asset 当前允许范围
```

跨 Workspace 复制需要显式进入 Asset Copy / Transfer 流程。

---

## 22. 跨 Workspace Copy

Resource Copy 到另一个 Workspace 时：

```text
原 Asset 引用
```

不能直接假设目标 Workspace 永久拥有访问权限。

系统应创建目标 Workspace 可合法访问的 Asset Identity。

底层 Blob 是否物理复用，由存储安全策略决定。

产品层不能出现：

```text
原 Workspace 删除 Asset
↓
目标 Workspace 文件突然消失
```

---

## 23. Duplicate Resource

同 Workspace Duplicate Resource：

```text
默认复用 Asset
```

而不是复制大型二进制文件。

新 Resource 中：

```text
assetId
```

可以继续引用同一个逻辑 Asset，或者通过内部引用关系复用 Blob。

具体逻辑 Asset 是否共享由实现决定。

但必须避免无意义的物理文件复制。

---

## 24. Asset Reference

系统必须能够知道：

```text
哪些 Resource 正在引用某个 Asset
```

用于：

- 删除安全判断
- Garbage Collection
- Cross Workspace Copy
- Resource Permanent Delete
- Usage / Quota
- Search / Preview

具体 Reference Index 实现由本地 AI 决定。

---

## 25. Reference 不能依赖全文扫描

不能在每次 Asset 删除时：

```text
扫描所有 Y.Doc
```

寻找 assetId。

系统需要维护可重建的 Asset Reference Index。

这个 Index 可以是派生状态。

如果丢失，应能通过 Resource Content 重新构建。

---

## 26. 引用删除

用户从一个 Document 删除图片：

```text
删除的是 Resource → Asset Reference
```

不是立即物理删除 Blob。

如果 Asset 仍被：

```text
其他 Node
其他 Resource
History
Trash
```

引用，Blob 继续保留。

---

## 27. Asset Trash

Asset 可以进入逻辑不可用 / Trash 状态。

但普通用户从正文移除文件时，不必立即把 Asset 本体 Trash。

Asset 生命周期主要由：

```text
Reference
Resource Lifecycle
Retention
```

决定。

---

## 28. Garbage Collection

Asset GC 必须满足：

```text
没有有效引用
+
Retention 已满足
+
没有受保护 History / Trash 引用
+
没有正在进行的 Task
```

以后才能进入 Purge。

不能简单使用：

```text
reference count == 0
↓
立即删除
```

因为并发、History 和异步任务都可能造成短时间引用变化。

---

## 29. Blob GC

Blob 可以在：

```text
没有任何有效 Asset 引用
```

且满足 Retention 后物理删除。

Blob GC 必须幂等，可重试。

失败不能产生不可追踪的孤儿状态。

---

## 30. Orphan Upload Cleanup

以下上传可能形成孤儿：

```text
Upload Session 创建
↓
用户关闭页面
↓
从未完成
```

或：

```text
Blob 已上传
↓
客户端未 Complete
```

系统必须定期清理：

```text
Expired Upload Session
Unclaimed Blob
Failed Processing Temp Files
```

具体过期时间由部署策略决定。

---

## 31. Resource Trash

Resource 进入 Trash 后：

```text
Asset Reference
```

继续有效。

这样 Restore Resource 后：

```text
图片
附件
视频
```

仍然可以恢复。

不能因为 Resource 进入 Trash 就立即删除其 Asset。

---

## 32. Resource Permanent Delete

Resource 永久删除后：

```text
该 Resource 的 Asset Reference
```

才进入最终释放流程。

Asset 是否随后被删除取决于：

```text
其他引用
History
Retention
Workspace Policy
```

---

## 33. History 与 Asset

History Preview 可能需要显示旧版本中的图片或附件。

因此：

```text
当前正文已经不引用 Asset
```

不等于：

```text
History 已经不需要 Asset
```

History Retention 与 Asset GC 必须协调。

---

## 34. History Retention 结束后

当相关历史版本已经被合法清理：

```text
History Reference
```

可以释放。

如果没有其他引用：

```text
Asset / Blob
```

才能进一步进入 GC。

---

## 35. Permission

Asset 访问不能只通过：

```text
知道 assetId
```

就直接下载。

系统必须验证：

```text
当前 Actor
+
Asset
+
关联 Workspace / Resource
+
当前访问能力
```

具体 Capability 由 Permission System 决定。

---

## 36. Download URL

下载 / 预览推荐使用：

```text
短期 Signed URL
```

或等价安全访问能力。

要求：

- 短期有效
- 可过期
- 不作为长期数据库字段
- 不写入 Y.Doc
- 不作为 Asset Identity
- 可按权限重新签发

---

## 37. 私有 Asset

默认 Asset 应视为：

```text
Private
```

除非产品明确支持公开资源。

Object Storage 不应默认公开整个 Bucket。

公开访问必须是明确产品能力。

---

## 38. CDN

图片、视频等读取量高的 Asset 可以通过 CDN 分发。

CDN 是读取加速层。

权限敏感资源需要：

```text
Signed URL
Signed Cookie
Tokenized Access
```

或等价控制。

CDN 缓存不能造成权限撤销后长期公开访问。

---

## 39. Range Request

视频、音频和大型 PDF 等需要支持：

```text
Range Request
```

以实现：

- Seek
- 分段加载
- 快速预览
- 避免整文件下载

具体能力依赖 Object Storage / CDN。

---

## 40. Image Processing

Image Asset 第一版建议支持后台生成：

```text
thumbnail
preview
optimized display variant
```

必要时支持：

```text
width variants
modern format
orientation normalization
```

原文件仍然保留。

UI 根据显示场景加载合适 Variant。

---

## 41. Video / Audio Processing

视频、音频处理可能很重。

第一版至少需要：

- 基础 Metadata 提取
- 可播放格式识别
- Thumbnail / Poster（视频）
- 长时任务状态

是否转码由产品需求决定。

转码必须作为：

```text
Async Task
```

不能阻塞 Upload Complete 主请求。

---

## 42. PDF / Document Preview

如果支持 PDF 或 Office Preview：

```text
Preview
```

属于 Asset 派生数据。

Preview 失败不能导致原文件丢失。

是否支持预览由 File Type Adapter 决定。

---

## 43. 派生文件

以下内容都属于 Derived Asset：

```text
thumbnail
preview
transcode
waveform
poster
optimized image
```

它们可以被重新生成。

不得把派生文件作为原始 Asset 的唯一真实副本。

---

## 44. Processing Task

重处理统一使用 Async Task。

任务必须：

- 可查询
- 可重试
- 可取消（安全时）
- 有失败状态
- 不依赖客户端持续在线

遵守 Unified Module Communication Design。

---

## 45. 安全扫描

生产环境必须预留文件安全扫描。

至少包括：

```text
malware scan
dangerous file detection
archive bomb protection
content type validation
```

具体安全产品由部署环境选择。

未通过扫描的文件不能进入 Ready。

---

## 46. Blocked Asset

安全策略拒绝的文件进入：

```text
Blocked
```

产品需要明确告诉用户：

```text
文件无法使用
```

不能只显示永久“处理中”。

Blocked 文件根据策略隔离和清理。

---

## 47. SVG / HTML 等主动内容

可能执行脚本的文件：

```text
SVG
HTML
```

不能直接按普通图片 / 文档信任。

需要：

- Sanitization
- Safe Render
- Forced Download
- Isolation

中的适当策略。

具体由 Security / File Type Adapter 决定。

---

## 48. Archive 文件

ZIP / TAR 等压缩包上传时必须防止：

```text
zip bomb
path traversal
extreme expansion
```

如果产品不需要在线解压：

```text
默认不在服务端自动解压用户 Archive
```

更安全。

---

## 49. Quota

Asset 模块必须支持 Quota。

至少可限制：

```text
单文件大小
Workspace 总存储
用户上传频率
同时进行的上传数量
大文件数量
派生任务资源
```

具体套餐额度由产品决定。

---

## 50. Quota 计算

Quota 不应简单按：

```text
Asset Metadata 数量
```

计算。

至少考虑：

```text
实际存储大小
派生文件
保留数据
共享 Blob 的计费策略
```

具体计费方式由产品定义。

---

## 51. 上传前检查

创建 Upload Session 时至少检查：

- Permission
- Workspace Lifecycle
- Quota
- File Size Limit
- File Type Policy
- Rate Limit

失败应在上传大文件前尽早返回。

---

## 52. 上传完成后再次验证

Upload Session 创建成功不代表最终文件必然合法。

Complete 后仍需验证：

```text
实际大小
实际类型
Hash
安全扫描
Workspace 状态
```

防止上传过程中状态变化或恶意客户端绕过前置检查。

---

## 53. 幂等

以下操作必须幂等：

```text
Create Upload Session
Complete Upload
Cancel Upload
Retry Processing
Create Asset
Delete Asset Reference
Purge Blob
```

客户端重试不能产生多个意外 Asset 或重复扣除 Quota。

---

## 54. 并发 Complete

客户端可能因为网络问题重复提交：

```text
Complete Upload
```

系统最终只能形成一个确定 Asset 状态。

不能重复启动大量相同派生任务。

---

## 55. 并发删除与引用

Resource A 删除 Asset Reference 的同时：

```text
Resource B
```

可能新增同一 Asset 引用。

Asset GC 必须基于权威引用状态和安全 Retention。

不能因为瞬间 reference count 变为 0 就直接物理删除。

---

## 56. 替换 Asset

用户“替换图片”默认表示：

```text
上传新 Asset
↓
Resource Reference 改为新 assetId
```

不是原地修改旧 Blob 内容。

这样：

- History 可正确显示旧文件
- 其他 Resource 引用不受影响
- CDN Cache 不混乱
- Asset Identity 语义稳定

---

## 57. Asset 内容不可变

推荐：

```text
Blob Content Immutable
```

上传完成后不在原 Blob 上修改二进制内容。

新内容：

```text
New Asset / Blob
```

这样简化：

- CDN
- Cache
- Hash
- History
- Dedup
- Security
- Recovery

---

## 58. Asset Metadata 可变

允许修改：

```text
display name
alt text（如果属于 Asset）
description
labels
```

但要区分：

```text
Resource-specific presentation
```

与：

```text
Asset global metadata
```

例如图片在不同 Document 中可以有不同：

```text
alt
caption
width
align
```

这些通常属于 Resource Node，而不是 Asset 本体。

---

## 59. EXIF 与隐私

图片可能包含：

```text
GPS
Device Info
Timestamp
```

系统应明确处理 EXIF。

可根据产品策略：

- 保留原文件
- 展示版本移除敏感 EXIF
- 下载原图时保留

不能无意识把 GPS Metadata 暴露到公开预览。

---

## 60. 文件下载名

下载时可以使用用户显示名。

但服务端必须安全生成：

```text
Content-Disposition
```

避免：

- Header Injection
- 路径字符问题
- 浏览器异常行为

具体实现由本地 AI 负责。

---

## 61. Cache

Asset 内容适合强缓存。

对于 Immutable Blob：

```text
long cache
content hash
```

可以显著降低成本。

权限检查与二进制缓存需要分离设计。

不要因为文件内容不可变，就让访问权限也永久缓存。

---

## 62. Asset Metadata Cache

Asset Metadata 可以缓存。

但以下变化需要失效：

```text
Blocked
Deleted
Permission Change
Workspace Lifecycle Change
Purge
```

不能让缓存导致已撤销文件继续可访问。

---

## 63. Storage Provider 抽象

Asset 系统不应让业务层依赖某一家 Object Storage 的专有字段。

可以使用：

```text
S3-compatible
Cloud Object Storage
Local Development Storage
```

具体 Provider 由部署环境决定。

Resource / Document 只认：

```text
assetId
```

---

## 64. Multi Region

第一版不要求立即做全球多 Region Blob 复制。

但架构不能假设：

```text
所有 Blob 永远只存在一台服务器本地磁盘
```

生产环境需要支持持久 Object Storage。

未来可以增加：

```text
CDN
Cross Region Replication
Data Residency
```

而不改变 Resource Schema。

---

## 65. Local Development

开发环境可以使用：

```text
Local Object Storage
S3-compatible emulator
```

但其行为应尽量模拟生产接口。

不能因为开发环境使用本地文件，就让业务代码直接保存绝对路径。

---

## 66. Backup

Object Storage 的 Backup / Versioning 策略属于基础设施。

但 Asset 模块必须保证：

```text
Metadata
Blob
Reference
```

能够在灾难恢复流程中重新关联。

详细 Backup / DR 在后续 Deployment / Disaster Recovery Design 中统一设计。

---

## 67. Search

Search 可以索引：

```text
file name
MIME
Asset metadata
OCR / transcript（以后）
```

但 Search 是派生系统。

Asset Ready 不依赖 Search 成功。

---

## 68. AI

AI 读取 Asset 必须：

- 有当前 Actor 权限
- 使用 assetId
- 通过受控读取接口
- 遵守文件大小和类型限制

AI 不应直接长期保存 Signed URL。

---

## 69. Plugin

Plugin 访问 Asset 同样受到：

```text
User Permission
+
Plugin Scope
+
Asset Access
```

限制。

Plugin 不应获得 Object Storage 主密钥。

---

## 70. Event

Asset 模块遵守 Unified Module Communication Design。

至少产生：

```text
UploadCreated
UploadCompleted
UploadFailed
AssetProcessingStarted
AssetReady
AssetBlocked
AssetDeleted
BlobPurged
```

事件只表达已发生事实。

---

## 71. Command

典型 Command：

```text
CreateUpload
CompleteUpload
CancelUpload
RetryAssetProcessing
DeleteAsset
RestoreAsset
PurgeAsset
```

Resource 插入图片等正文修改：

```text
不由 Asset Command 直接修改 Y.Doc
```

而由 Resource / Document Command 负责建立 assetId 引用。

---

## 72. Query

典型 Query：

```text
GetAsset
GetAssetAccess
GetAssetPreview
ListResourceAssets
GetUploadStatus
GetProcessingStatus
```

大文件正文不通过普通 Query 返回。

---

## 73. 错误模型

至少区分：

```text
Permission Denied
Quota Exceeded
File Too Large
Unsupported Type
Upload Expired
Upload Incomplete
Checksum Mismatch
Malware Detected
Processing Failed
Asset Not Found
Asset Not Ready
Asset Deleted
Storage Unavailable
```

具体错误码遵守统一通信规范。

---

## 74. Storage 故障

Object Storage 暂时不可用时：

- 不伪造上传成功
- 不把 Asset 标记 Ready
- 已有 Resource 正文编辑继续
- 无关 Resource 不受影响
- Processing Task 可重试
- 下载失败提供明确错误

Asset 故障不能拖垮 Realtime Collaboration。

---

## 75. Processing 故障

Thumbnail / Preview / Transcode 失败：

```text
不能损坏原始 Asset
```

如果原文件安全且可下载：

```text
Asset 可以保持 Ready
Derived Variant = Failed
```

具体产品策略由文件类型决定。

---

## 76. 可观测性

至少监控：

```text
upload count
upload bytes
upload duration
upload failure
multipart retry
orphan upload count
processing duration
processing failure
scan failure
blocked asset count
download latency
download bytes
signed URL issue count
asset reference count
GC candidates
GC failure
blob purge duration
storage usage
quota rejection
CDN hit rate
preview generation latency
```

---

## 77. 安全审计

至少审计：

```text
Blocked File
Malware Detection
Large Download
Sensitive Share Access
Permanent Asset Delete
Cross Workspace Copy
Admin Override
```

普通图片查看不需要全部进入高成本安全审计。

---

## 78. 第一版不做

第一版暂不实现：

```text
公共文件市场
跨 Workspace 自动共享 Asset
P2P 文件传输
用户自定义 Storage Provider
任意文件在线执行
服务端自动解压所有 Archive
永久公开 Bucket
全局用户可见 Hash 去重
复杂媒体编辑
完整 DAM 数字资产管理系统
```

---

## 79. 核心验收场景

### 场景 1：图片上传

用户在 Document 中插入图片。

结果：

```text
占位显示
↓
直接上传 Object Storage
↓
校验 / 扫描
↓
Asset Ready
↓
所有协作者显示图片
```

正文编辑不中断。

---

### 场景 2：中文文件名

上传：

```text
系统架构最终版.png
```

结果：

- 正常上传
- 正常显示
- 内部身份不依赖文件名
- 下载名正确

---

### 场景 3：大文件断线

上传大型视频时网络断开。

结果：

```text
恢复网络
↓
继续未完成部分
```

而不是重新上传全部内容。

---

### 场景 4：重复 Complete

客户端因超时重复 Complete。

结果：

- 最终只形成一个逻辑上传结果
- 不重复扣 Quota
- 不无限重复启动 Processing

---

### 场景 5：错误文件类型

用户把可执行内容伪装成：

```text
photo.jpg
```

结果：

- 服务端实际类型验证发现异常
- 不进入正常 Ready
- 用户收到明确错误

---

### 场景 6：恶意文件

安全扫描发现 Malware。

结果：

```text
Asset → Blocked
```

不能被正常预览或下载。

---

### 场景 7：Duplicate Resource

Document A 有 20 张图片。

用户 Duplicate Document。

结果：

- 新 Resource 快速创建
- 不复制 20 份二进制
- Asset 正常显示
- 新 Resource History 独立

---

### 场景 8：删除正文图片

用户从 Document 删除图片 Node。

结果：

- 删除 Reference
- Blob 不立即删除
- History 仍可预览旧版本

---

### 场景 9：Resource Trash

Resource 进入 Trash。

结果：

- Asset 保留
- Restore 后所有附件正常恢复

---

### 场景 10：Resource Permanent Delete

Resource 永久删除。

结果：

- 释放该 Resource Reference
- 仍被其他 Resource / History 引用的 Asset 保留
- 无任何有效引用且 Retention 满足后才 GC

---

### 场景 11：跨 Workspace Copy

Resource Copy 到另一 Workspace。

结果：

- 目标 Workspace 拥有独立合法 Asset 访问关系
- 原 Workspace 后续删除不破坏目标 Workspace
- 物理 Blob 是否复用对产品透明

---

### 场景 12：权限撤销

User A 曾能查看包含图片的 Resource。

权限被移除。

结果：

- 新 Signed URL 无法获取
- 旧短期 URL 按过期策略失效
- 不能仅凭 assetId 永久下载

---

### 场景 13：Preview 失败

原 PDF 上传成功，但 Preview 生成失败。

结果：

- 原文件保持安全可下载
- Preview 显示处理失败
- 可以后台重试
- 不损坏 Asset

---

### 场景 14：Storage 故障

Object Storage 短暂异常。

结果：

- Resource 文本实时编辑继续
- Upload / Download 显示明确失败或重试
- 不影响 Permission / Realtime / History 主链

---

### 场景 15：Orphan Upload

用户创建 Upload Session 后直接关闭浏览器。

结果：

- Session 到期
- 临时 Blob 最终被清理
- 不长期占用 Quota / Storage

---

### 场景 16：高并发上传

大量用户同时上传。

结果：

- 应用服务不承担所有文件二进制转发
- Object Storage 承担主要数据面
- Metadata / Permission 服务保持可用
- 有 Rate Limit / Quota / Backpressure

---

## 80. 本地 AI 实现自由度

本设计不规定：

- 必须使用哪家 Object Storage
- Upload Session 的数据库表结构
- Multipart 的具体 Part 大小
- Hash 算法具体库
- Malware Scanner 产品
- CDN 厂商
- Thumbnail 库
- 视频转码工具
- Signed URL 的具体实现
- Reference Index 的存储形式
- GC Worker 数量
- Retention 固定天数

本地 AI 可以根据现有项目技术栈、部署环境和压力测试选择。

但必须满足本设计的功能、安全、生命周期、性能与验收要求。

---

## 81. 架构硬约束

1. Asset 与 Resource 分离。
2. Resource 正文只保存稳定 `assetId` 或等价稳定引用。
3. 不把 Base64、大型二进制、临时 Signed URL 写入 Y.Doc。
4. Asset 不创建独立 Y.Doc / Resource Session。
5. 大文件优先 Direct Upload 到 Object Storage。
6. 上传使用短生命周期 Upload Session。
7. 大文件必须支持断点续传或等价能力。
8. Upload Complete 后必须再次校验实际文件。
9. 文件类型不能只信任扩展名和客户端 MIME。
10. Asset 只有通过必要校验和安全处理后才能 Ready。
11. Asset 使用稳定 assetId，物理 Storage Key 不暴露给业务模块。
12. 推荐逻辑 Asset 与物理 Blob 分离。
13. Blob 内容推荐 Immutable。
14. Duplicate Resource 不无意义复制大型二进制。
15. Cross Workspace Copy 必须建立目标 Workspace 合法 Asset 访问关系。
16. Asset 访问必须经过 Permission，不允许仅凭 assetId 永久读取。
17. Signed URL 必须短期有效，不能作为长期身份。
18. Resource Trash 不立即删除 Asset。
19. History 仍引用的 Asset 不能被 GC。
20. Asset GC 必须考虑 Reference、Retention、History、Trash 和并发。
21. Orphan Upload 必须自动清理。
22. 派生 Preview / Thumbnail 失败不能破坏原始文件。
23. 高风险文件必须支持扫描、隔离和 Blocked 状态。
24. Asset 故障不能阻塞 Realtime Collaboration 主链。
25. Asset 处理长任务遵守统一 Async Task 模型。
26. Asset 模块遵守 Unified Module Communication Design。
27. 业务模块不能依赖 Object Storage Provider 的内部字段。
28. Project / Resource Tree 查询不能加载 Asset 二进制。
29. Asset Storage 必须支持生产级持久 Object Storage，而不是依赖单机本地磁盘。
30. 文件名称原生支持 Unicode 和非英语用户。

---

## 82. 最终模型

```text
Resource
│
└── Node / Content
    │
    └── assetId
          │
          ▼
        Asset
          │
          ├── Metadata
          ├── Permission Context
          ├── Processing State
          ├── Derived Variants
          └── Blob Reference
                 │
                 ▼
               Blob
                 │
                 └── Object Storage / CDN
```

上传：

```text
Client
↓
Create Upload Session
↓
Permission / Quota / Policy
↓
Direct Upload
↓
Verify
↓
Scan
↓
Process
↓
Asset Ready
↓
Resource 引用 assetId
```

删除：

```text
Resource Reference Removed
↓
History / Trash / Other References 检查
↓
Retention
↓
Asset GC
↓
Blob GC
```

系统必须保证：

> 二进制文件走自己的高吞吐存储链，实时文档只保存稳定引用；文件上传、处理、预览和删除都不能重新把大文件塞回实时协作主路径。
